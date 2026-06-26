// Example frontend configuration — copy to config.js for local development.
// In production, FrontendStack auto-generates config.js from SSM Parameter Store values.
window.BACKENDS = {
    ec2:    { url: "/ec2-api", ws: null, label: "⚡ EC2 (Traditional)", color: "#ea580c" },
    ecs:    { url: "/ecs-api", ws: null, label: "🐳 ECS (Container)", color: "#2563eb" },
    lambda: { url: "https://YOUR_REST_API_ID.execute-api.eu-west-2.amazonaws.com/prod", ws: "wss://YOUR_WS_API_ID.execute-api.eu-west-2.amazonaws.com/prod", label: "λ Lambda (Serverless)", color: "#7c3aed" }
};
window.WS_URL = "wss://YOUR_WS_API_ID.execute-api.eu-west-2.amazonaws.com/prod";
window.API_URL = "http://localhost:8000";
