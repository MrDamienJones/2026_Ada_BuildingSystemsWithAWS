"""Seed DynamoDB with poll data from polls.json."""

import json

import boto3

dynamodb = boto3.resource("dynamodb", region_name="eu-west-2")
table = dynamodb.Table("live-poll-app")

with open("cdk/seed_data/polls.json") as f:
    polls = json.load(f)

for poll in polls:
    poll_id = poll["poll_id"]
    table.put_item(
        Item={
            "PK": f"POLL#{poll_id}",
            "SK": "META",
            "question": poll["question"],
            "visible": False,
            "created_at": "2024-01-01T00:00:00Z",
        }
    )
    for option in poll.get("options", []):
        table.put_item(
            Item={
                "PK": f"POLL#{poll_id}",
                "SK": f"OPTION#{option['option_id']}",
                "label": option["label"],
                "order": option.get("order", 0),
            }
        )

print(f"Seeded {len(polls)} polls successfully")
