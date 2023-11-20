import os

from bson import ObjectId
from flask import Flask, jsonify, make_response, request
from flask_jwt_extended import JWTManager

from settings import db_client

app = Flask(__name__)
#app = Flask(_name_)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024  * 1024 

from urls import posts_blueprint

app.register_blueprint(posts_blueprint)
app.config["JWT_SECRET_KEY"] = os.environ["JWT_SECRET_KEY"]
jwt = JWTManager(app)

@jwt.unauthorized_loader
def unauthorized_response(callback):
    response = {"message": "Missing Authorization Header"}
    return make_response(jsonify(response), 401)

@jwt.token_in_blocklist_loader
def check_token_in_blacklist(jwt_header, jwt_payload):
    auth_token = request.environ.get("HTTP_AUTHORIZATION").split(" ")[-1]
    user_id = jwt_payload["sub"]
    user_obj = db_client.Users.find_one(
        {"_id": ObjectId(user_id), "blacklistedTokens": auth_token},
    )
    if user_obj:
        response = {"message": "The token provided has expired."}
        return make_response(jsonify(response), 401)
