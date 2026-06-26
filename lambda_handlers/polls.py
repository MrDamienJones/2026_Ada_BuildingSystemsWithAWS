"""Lambda handler for REST API Gateway events.

Wraps the FastAPI application using the Mangum adapter so that API Gateway
REST proxy events are translated into ASGI requests and responses.

Validates: Requirements 9.1, 9.6
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
