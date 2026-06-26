"""EC2 CDK stack for the Live Poll App.

Deploys the Backend API on EC2 instances behind an Application Load Balancer
with an Auto Scaling Group, demonstrating the traditional hosting model.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import (
    aws_autoscaling as autoscaling,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_elasticloadbalancingv2 as elbv2,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_s3_assets as s3_assets,
)
from aws_cdk import (
    aws_ssm as ssm,
)
from cdk_config import AWS_REGION, PRESENTER_SECRET_KEY
from constructs import Construct
from shared_stack import SharedStack


class EC2Stack(Stack):
    """EC2 deployment stack for the Live Poll App.

    Provisions:
    - Auto Scaling Group (t3.micro, min=1, max=3)
    - Application Load Balancer for stable DNS endpoint
    - Security groups for ALB and instances
    - IAM instance role with DynamoDB read/write permissions
    - User data script installing deps, copying app code, configuring systemd
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        shared_stack: SharedStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- VPC (default VPC) ---
        vpc = ec2.Vpc.from_lookup(self, "DefaultVPC", is_default=True)

        # --- Security Group for ALB ---
        alb_sg = ec2.SecurityGroup(
            self,
            "AlbSG",
            vpc=vpc,
            description="Allow inbound HTTP on port 80 to ALB",
            allow_all_outbound=True,
        )
        alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from anywhere",
        )

        # --- Security Group for EC2 instances (only from ALB) ---
        instance_sg = ec2.SecurityGroup(
            self,
            "InstanceSG",
            vpc=vpc,
            description="Allow HTTP from ALB only",
            allow_all_outbound=True,
        )
        instance_sg.add_ingress_rule(
            peer=alb_sg,
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from ALB",
        )

        # --- IAM Role for EC2 with DynamoDB access ---
        role = iam.Role(
            self,
            "EC2InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="IAM role for Live Poll App EC2 instances",
        )
        shared_stack.main_table.grant_read_write_data(role)
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )

        # --- Bundle application code as an S3 asset ---
        app_asset = s3_assets.Asset(
            self,
            "AppCodeAsset",
            path="app",
        )
        app_asset.grant_read(role)

        # --- User Data Script ---
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "#!/bin/bash",
            "set -euxo pipefail",
            "",
            "# Update system packages",
            "dnf update -y",
            "",
            "# Install Python 3.11 and pip",
            "dnf install -y python3.11 python3.11-pip unzip",
            "",
            "# Create application directory",
            "mkdir -p /opt/poll-app",
            "",
            "# Download application code from S3 asset",
            f"aws s3 cp {app_asset.s3_object_url} /tmp/app-code.zip",
            "cd /opt/poll-app",
            "unzip -o /tmp/app-code.zip -d /opt/poll-app/app",
            "rm -f /tmp/app-code.zip",
            "",
            "# Install Python dependencies",
            "python3.11 -m pip install fastapi uvicorn boto3 pydantic pydantic-settings",
            "",
            "# Create systemd service unit",
            "cat > /etc/systemd/system/poll-app.service << 'EOF'",
            "[Unit]",
            "Description=Live Poll App - FastAPI Backend",
            "After=network.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            "User=root",
            "WorkingDirectory=/opt/poll-app",
            f"Environment=DYNAMODB_TABLE={shared_stack.main_table.table_name}",
            f"Environment=AWS_REGION={AWS_REGION}",
            f"Environment=PRESENTER_SECRET_KEY={PRESENTER_SECRET_KEY}",
            "Environment=ALLOWED_ORIGINS=*",
            "ExecStart=/usr/bin/python3.11 -m uvicorn app.main:app --host 0.0.0.0 --port 80",
            "Restart=always",
            "RestartSec=3",
            "StandardOutput=journal",
            "StandardError=journal",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "EOF",
            "",
            "# Enable and start the service",
            "systemctl daemon-reload",
            "systemctl enable poll-app.service",
            "systemctl start poll-app.service",
        )

        # --- Launch Template ---
        launch_template = ec2.LaunchTemplate(
            self,
            "PollAppLT",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            role=role,
            user_data=user_data,
            security_group=instance_sg,
            associate_public_ip_address=True,
        )

        # --- Auto Scaling Group ---
        asg = autoscaling.AutoScalingGroup(
            self,
            "PollAppASG",
            vpc=vpc,
            launch_template=launch_template,
            min_capacity=1,
            max_capacity=3,
            desired_capacity=1,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            health_check=autoscaling.HealthCheck.elb(grace=Duration.seconds(120)),
        )

        # --- Application Load Balancer ---
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "PollAppALB",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
        )

        listener = alb.add_listener("HttpListener", port=80, open=False)
        listener.add_targets(
            "EC2Targets",
            port=80,
            targets=[asg],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )

        # --- Store EC2 ALB URL in SSM for the frontend stack ---
        ssm.StringParameter(
            self,
            "Ec2UrlParam",
            parameter_name="/live-poll/ec2-url",
            string_value="http://" + alb.load_balancer_dns_name,
        )

        # --- CDK Output: ALB DNS name ---
        CfnOutput(
            self,
            "EC2AlbUrl",
            value="http://" + alb.load_balancer_dns_name,
            description="ALB URL for the Live Poll App EC2 instances",
        )
