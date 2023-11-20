import traceback
import requests
import base64
import io
import mimetypes
from datetime import datetime
from statistics import mode
from collections import Counter

from boto3.s3.transfer import TransferConfig
from bson import ObjectId
from flask import request, jsonify, make_response
from flask.views import MethodView
from flask_jwt_extended import jwt_required, get_jwt_identity

from handlers import PostHandler, PostActivityHandler
from utils import add_user_info
from settings import db_client,bucket_name,s3_client,s3
import os


class GetSignedUrlsView(MethodView):

    @jwt_required()
    def get(self):
        try:
            file_names = request.args["fileNames"]
            user_id = get_jwt_identity()
            response = {"data": PostHandler().get_pre_signed_post_urls(user_id, file_names)}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to fetch signed url."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)
        
# class FileUploadView(MethodView):

#     @jwt_required()
#     def post(self):
#         try:
#             content_data = []            
#             count=0
#             request_data = request.form
#             user_id = get_jwt_identity()

#             files = request.files.getlist("file")
#             for file in files:
#                 data={}
#                 count=count+1
                              
#                 file_name=file.filename
#                 mimetypes.add_type('image/jpeg', '.jpeg')
#                 mimetypes.add_type('image/gif', '.gif')
#                 mimetypes.add_type('image/png', '.png')
#                 mimetypes.add_type('audio/mpeg', '.mp4')
#                 mimetypes.add_type('audio/mpeg', '.avi')
#                 mimetypes.add_type('audio/mpeg', '.mpeg4')
#                 file_mime_type, _ = mimetypes.guess_type(file_name)
#                 # file_mime_type=file.content_type
#                 upload_id = ObjectId()
#                 file_key = user_id + "-" + str(upload_id) + "-" + file_name
#                 res=s3_client.upload_fileobj(file, bucket_name,file_key,ExtraArgs={'ContentType': file_mime_type} )
#                 data["uploadId"] = str(upload_id)
#                 data["name"]=file_name
#                 data["type"]=file_mime_type
#                 data["sequence"]=count  
#                 content_data.append(data)
            
#             response = {"data": content_data}
#             response_code = 200
           
#         except Exception as e:
#             print(e)
#             traceback.print_exc()
#             response = {"message": "Unable to upload file."}   
#             response_code = 500

#         response["statusCode"] = response_code
#         return make_response(jsonify(response), response_code)
class FileUploadView(MethodView):

    @jwt_required()
    def post(self):
        try:
            content_data = []
            count = 0

            for file in request.files.getlist("file"):
                print(request.files.getlist("file"))
                print(file)

                count += 1
                data = {}
                
                file_name = file.filename
                mimetypes.add_type('image/jpeg', '.jpeg')
                mimetypes.add_type('image/gif', '.gif')
                mimetypes.add_type('image/png', '.png')
                mimetypes.add_type('audio/mpeg', '.mp4')
                mimetypes.add_type('audio/mpeg', '.avi')
                mimetypes.add_type('audio/mpeg', '.mpeg4')
                
                file_mime_type, _ = mimetypes.guess_type(file_name)
                upload_id = ObjectId()
                print(upload_id)
                
                current_time = datetime.now()
                formatted_time = current_time.strftime('%Y%m%d%H%M%S')
                
                key = file_name.split(".")
                key = key[0] + formatted_time + "." + key[1]
                # file_key = f"{file_name}-{formatted_time}"
                
                res = s3_client.upload_fileobj(file, bucket_name, key, ExtraArgs={'ContentType': file_mime_type})

                data["uploadId"] = str(upload_id)
                data["name"] = key
                data["type"] = file_mime_type
                data["sequence"] = count
                content_data.append(data)

            response = {"data": content_data}
            response_code = 200

        except Exception as e:
            print(e)
            traceback.print_exc()
            response = {"message": "Unable to upload file."}   
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)
          
class ManagePostsView(MethodView):

    @add_user_info
    @jwt_required()
    def get(self):
        try:

            query_params = request.args
            user_id = get_jwt_identity()
            response = PostHandler().get_user_feed_posts(user_id, query_params)
            response_code = 200
            
            if response['data']== []:
                response = PostHandler().get_user_feed_posts(user_id, query_params)
                response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to fetch user feed."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

    @jwt_required()
    def post(self):
        try:

            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())
            query_params = request.args
            PostHandler().create_post(user_id, data, query_params)
            response = {"message": "Post created successfully."}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to create post."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)


class ManagePostView(MethodView):

    @jwt_required()
    def patch(self, post_id):

        response_code = None
        try:
            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())

            if data.get("markAsInappropriate"):
                PostHandler().mark_inappropriate(user_id, post_id, data)
                response = {"message": "Post flagged as inappropriate"}
                response_code = 200

            elif data.get("status") and data["status"] in ["SAVED", "INACTIVE"]:
                new_status = data["status"]
                response, response_code = PostHandler().change_status(user_id, post_id, new_status)
            
            elif data.get("caption"):
                response, response_code = PostHandler().edit_caption(user_id, post_id, data["caption"])
            
            elif data.get("visibleTo"):
                response, response_code = PostHandler().edit_visibleTo(user_id, post_id, data["visibleTo"])
                
            elif data.get("hashtags"):
                response, response_code = PostHandler().edit_hashtags(user_id, post_id, data["hashtags"])
                
            elif data.get("categoryId"):
                response, response_code = PostHandler().edit_category(user_id, post_id, data["categoryId"])

            elif data.get("24hour_status") and data["24hour_status"] in ["SAVED", "REJECTED"]:
                response, response_code = PostHandler().edit_24hour_status(user_id, post_id, data["24hour_status"])
            
            else:
                response = {"message": "Invalid request body."}
                response_code = 400

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to update post details."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)
    
    @jwt_required()
    def delete(self, post_id):
        try:
            user_id = ObjectId(get_jwt_identity())
            query_params = request.args
            
            if query_params.get("upload_id"):
                response, response_code= PostHandler().delete_upload(user_id, post_id,query_params["upload_id"])
            else:
                PostHandler().delete_post(user_id, post_id)
                response = {"message": "Post deleted successfully."}
                response_code = 200         
            
        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to delete post."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)
        

class ManagePostComments(MethodView):

    @add_user_info
    @jwt_required()
    def get(self, post_id):
        try:
            query_params = request.args
            user_id = ObjectId(get_jwt_identity())
            post_user=db_client.Posts.find_one({"_id":ObjectId(post_id)},{"_id":0,"commentBox":1})
            if post_user.get("commentBox")==True:
                response = PostActivityHandler().get_post_comments(user_id, post_id, query_params)
                response_code = 200
            else:
                response = {"message": "comment box turned off"}
                response_code = 200          
            
        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to fetch comments."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

    @jwt_required()
    def post(self, post_id):

        try:
            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())
            post_user=db_client.Posts.find_one({"_id":ObjectId(post_id)},{"_id":0,"commentBox":1})
            if post_user.get("commentBox")==True:
                PostActivityHandler().add_comment(user_id, post_id, data["comment"], data["commentType"])
                response = {"message": "Comment added"}
                response_code = 200
            else:
                response = {"message": "comment box turned off"}
                response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to add comment."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

    @jwt_required()
    def patch(self, post_id):
        try: 
            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())
            query_params = request.args
            post_user=db_client.Posts.find_one({"_id":ObjectId(post_id)},{"_id":0,"commentBox":1})
            if post_user.get("commentBox")==True:
                PostActivityHandler().update_comment(user_id, post_id, data["comment"],data["commentType"],query_params)
                response = {"message": "Comment updated"}
                response_code = 200
            else:
                response = {"message": "comment box turned off"}
                response_code = 500
           
        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to update comment."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)       


    @jwt_required()
    def delete(self, post_id):
        try:
            data = request.args
            comment_id=data["comment_id"]
            user_id = ObjectId(get_jwt_identity())
            post_user=db_client.Posts.find_one({"_id":ObjectId(post_id)},{"_id":0,"commentBox":1}) or {}
            if post_user.get("commentBox")==True:
                PostActivityHandler().remove_comment(user_id, post_id,comment_id)
                response = {"message": "comment removed"}
                response_code = 200
            else:
                response = {"message": "comment box turned off"}
                response_code = 200    

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to remove comment."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)

class ManageCommentsReply(MethodView):

    @add_user_info
    @jwt_required()
    def get(self, comment_id):
        try:
            user_id = ObjectId(get_jwt_identity())
            response = PostActivityHandler().get_comment_reply(user_id, comment_id)
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to fetch comment reply."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

    @jwt_required()
    def post(self, comment_id):

        try:
            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())
            PostActivityHandler().add_comment_reply(user_id, comment_id, data["reply"], data["replyType"])
            response = {"message": "Comment reply added"}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to add comment reply."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)
    
    @jwt_required()
    def patch(self, comment_id):
        try: 
            data = request.get_json()
            query_params = request.args
            user_id = ObjectId(get_jwt_identity())
            PostActivityHandler().update_comment_reply(user_id, comment_id, data["reply"],data["replyType"],query_params)
            response = {"message": "reply updated"}
            response_code = 200
           
        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to update reply."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200) 

    @jwt_required()
    def delete(self, comment_id):
        try:
            data = request.get_json()
            reply_id=data["reply_id"]
            user_id = ObjectId(get_jwt_identity())
            PostActivityHandler().remove_comment_reply(user_id, comment_id, reply_id)
            response = {"message": "comment reply removed"}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to remove comment."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)

class ManagePostReactions(MethodView):

    @add_user_info
    @jwt_required()
    def get(self, post_id):
        try:
            query_params = request.args
            user_id = ObjectId(get_jwt_identity())
            response = PostActivityHandler().get_post_reactions(user_id, post_id, query_params)
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to fetch reactions."}
            response_code = 500

            

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

    @jwt_required()
    def post(self, post_id):
        try:
            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())
            query={
            "createdBy": user_id,
            "postId": ObjectId(post_id),
            "status": "ACTIVE"
            }
            react=db_client.PostReactions.find_one(query)
            if react:
                response = {"message": "you already added a reaction added","sentReactionType":data["reactionType"]}
                response_code = 200
            else:
                PostActivityHandler().add_reaction(user_id, post_id, data)
                response = {"message": "Reaction added","sentReactionType":data["reactionType"]}
                response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to add reaction."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)
    
    @jwt_required()
    def patch(self, post_id):
        try:
            data = request.get_json()
            user_id = ObjectId(get_jwt_identity())
            if PostActivityHandler().update_reaction(user_id, post_id, data["reactionType"]):
                response = {"message": "Reaction updated","sentReactionType":data["reactionType"]}
                response_code = 200
            else:
                response = {"message": "Reaction does not exist"}
                response_code = 200


        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to update reaction.","sentReactionType":data["reactionType"]}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)

    @jwt_required()
    def delete(self, post_id):
        try:
            user_id = ObjectId(get_jwt_identity())
            PostActivityHandler().remove_reaction(user_id, post_id)
            response = {"message": "Reaction removed"}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to remove reaction."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code or 200)


class AddUploadViews(MethodView):

    @jwt_required()
    def post(self, post_id, upload_id):

        try:
            user_id = ObjectId(get_jwt_identity())
            PostHandler().add_upload_view(user_id, post_id, upload_id)
            response = {"message": "View added"}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to add view."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

class getVideoView(MethodView):

    @jwt_required()
    def get(self):

        try:
            query_params = request.args
            user_id = ObjectId(get_jwt_identity())  
            response = PostHandler().get_video(user_id,query_params)
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to get videos."}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

class ManagePendingPosts(MethodView):

    @jwt_required()
    def get(self):

        try:
            user_id = ObjectId(get_jwt_identity()) 

            projection={
                "_id":0,
                "caption": 1,
                "comments": 1,
                "createdOn": 1,
                "hashtags": 1,
                "category": 1,
                "reactions": 1,
                "updatedOn": 1,
            }

            posts=list(
            db_client["Posts"].find({"createdBy":user_id,"24hour_status":"PENDING"}, projection=projection).sort("createdOn", -1)# fetched an extra doc to power pagination logic
            ) or []
            for i in posts:
                diff = datetime.now() - i.get("createdOn")
                
                days, seconds = diff.days, diff.seconds
                hours = days * 24 + seconds // 3600
                print(hours)
                
                if hours < 24:
                    posts.remove(i)

            print(posts)
            response = {"data": posts}
            response_code = 200       
            
        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to get posts with pending status"}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)

class ManageRandomPosts(MethodView):

    @jwt_required()
    def get(self):
        try:
            user_id = ObjectId(get_jwt_identity())

            random_posts=db_client.PostUploads.aggregate([{ "$sample": { "size": 20 } }])
            random_upload=[]
            j=0
            for i in random_posts:                                           
                if j<=10 and i.get("status")=="ACTIVE":
                    react=db_client.Posts.find_one({"_id":i["postId"]},{"reactions":1,"_id":0}) or {}
                    j=j+1
                    
                    upload_url = {
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{i.get('key')}",
                        "status": "NO REQUESTS",
                        "_id": str(user_id),
                        "type": i.get("type"),
                        "upload_id": str(i["_id"]),
                        "views": i["views"]
                    }
                    upload={**upload_url,**react}
                    random_upload.append(upload)
                    
            response = {"data": random_upload}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to get random"}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)      

class ManageTrendingHash(MethodView):

    @jwt_required()
    def get(self):
        try:
            hash_list=[]
            hashtags=[]

            hash=db_client.Posts.find({"status":"ACTIVE"},{"hashtags":1})
            for i in hash:
                for j in i["hashtags"]:
                    hash_list.append(j)

            c = Counter(hash_list)
            hastags_counts = [{"hashtag": key, "count": value} for key, value in c.most_common(10)]

            response = {"data": hastags_counts}
            response_code = 200

        except Exception:
            traceback.print_exc()
            response = {"message": "Unable to get trending hashtags"}
            response_code = 500

        response["statusCode"] = response_code
        return make_response(jsonify(response), response_code)


class HidePostView(MethodView):
    @jwt_required()
    def post(self, post_id):
        try:
            # Extract necessary data from the request
            user_id = get_jwt_identity()

            db_client["HidePosts"].insert_one({
                "postId": post_id,
                "userId": user_id,
                "status":"Hidden",
                "createdOn": datetime.now(),
                "updatedOn": datetime.now()
                
            })

            response = {"message": "Post hidden successfully"}
            return jsonify(response), 200

        except Exception as e:
            response = {"message": "Unable to hide post", "error": str(e)}
            return jsonify(response), 500

class UnHidePostView(MethodView):
    @jwt_required()
    def post(self, post_id):
        try:
            # Extract necessary data from the request
            user_id = get_jwt_identity()

            # Update the status of the post from "hidden" to "unhidden" in the HidePosts collection
            db_client["HidePosts"].update_one(
                {"postId": post_id, "userId": user_id},
                {
                    "$set": {
                        "status": "unhidden",
                        "updatedOn": datetime.now()
                    }
                }
            )

            response = {"message": "Post unhidden successfully"}
            return jsonify(response), 200

        except Exception as e:
            response = {"message": "Unable to unhide post", "error": str(e)}
            return jsonify(response), 500
class BlockPostView(MethodView):
    @jwt_required()
    def post(self, post_id):
        try:
            user_id = ObjectId(get_jwt_identity())

            db_client["BlockPosts"].insert_one({
                "postId": post_id,
                "userId": user_id,
                "status":"Blocked",
                "createdOn": datetime.now(),
                "updatedOn": datetime.now()
                
            })

            response = {"message": "Post blocked successfully"}
            return jsonify(response), 200

        except Exception as e:
            response = {"message": "Unable to block post", "error": str(e)}
            return jsonify(response), 500

class UnblockPostView(MethodView):
    @jwt_required()
    def post(self, post_id):
        try:
            # Extract necessary data from the request
            user_id = ObjectId(get_jwt_identity())

            # Update post status to "unblocked" in the database
            db_client["BlockPosts"].update_one(
                {"postId": post_id, "userId": user_id},
                {
                    "$set": {
                        "status": "unBlocked",
                        "updatedOn": datetime.now()
                    }
                }
            )

            response = {"message": "Post unblocked successfully"}
            return jsonify(response), 200

        except Exception as e:
            response = {"message": "Unable to unblock post", "error": str(e)}
            return jsonify(response), 500

class RadiusSettingView(MethodView):
    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            data = request.get_json()

            radius = int(data.get("radius", 0)) 

            if 2000 <= radius <= 20000:
                db_client.Users.update_one({"_id": ObjectId(user_id)}, {"$set": {"radius": radius}})

                response_data = {
                    "message": "Radius updated successfully",
                    "radius": radius,
                    "responce_code":200
                }

                return jsonify(response_data), 200
            else:
                response_data = {
                    "message": "Invalid or missing radius value"
                }

                return jsonify(response_data), 400

        except Exception as e:
            response = {"message": "Internet server error", "error": str(e)}
            return jsonify(response), 500
    @jwt_required()
    def get(self):
        try:
            user_id = get_jwt_identity()
            
            user = db_client.Users.find_one({"_id":ObjectId(user_id)}, {"radius": 1})

            if user:
                radius = user.get("radius", 0)
                response_data = {
                    "data": radius,
                    "message":"radius retrived succesfully",
                    "responce_code":200
                }
                return jsonify(response_data), 200
            else:
                response_data = {
                    "message": "User not found"
                }
                return jsonify(response_data), 200

        except Exception as e:
            response_data = {
                "message": "Internal Server Error",
                "error": str(e)
            }
            return jsonify(response_data), 500

class PostDeeplinkingView(MethodView):
    def get(self):
        try:
            query_params = request.args
            response_code = 200
            response_data = {}  # Define a default value for response_data

            if query_params.get("post_id"):
                post_id = query_params["post_id"]
                post_data = PostHandler().get_post_by_id(post_id)
                response_data = post_data
            else:
                response_data = {"message": "No 'post_id' provided in the query parameters", "statusCode": 400}
                response_code = 400

        except Exception as e:
            response_data = {"message": "Unable to fetch user feed", "error": str(e), "statusCode": 500}
            response_code = 500

        return jsonify(response_data), response_code 
    


