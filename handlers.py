from logging import captureWarnings
import re
import os
import boto3
import tempfile 
import string
import random    
  
from bson import regex, ObjectId
from collections import Counter
from datetime import datetime
import mimetypes
from collections import ChainMap


from settings import bucket_name, db_client, s3_client


class PostHandler:

    def get_pre_signed_post_urls(self, user_id, file_names):
        file_urls = []
        file_names = file_names.split(",")
        for file_name in file_names:
            f=file_name
            mimetypes.add_type('image/jpeg', '.jpeg')
            mimetypes.add_type('image/tiff', '.tiff')
            mimetypes.add_type('image/gif', '.gif')
            mimetypes.add_type('image/png', '.png')
            mimetypes.add_type('audio/mpeg', '.mp4')
            mimetypes.add_type('audio/mpeg', '.mpeg4')
            file_mime_type, _ = mimetypes.guess_type(file_name)
            upload_id = ObjectId()
            file_key = user_id + "-" + str(upload_id) + "-" + f
            file_url = s3_client.generate_presigned_post(
                Bucket=bucket_name,
                Key=file_key,
                Fields={
                    "acl": "private",
                    "Content-Type" : file_mime_type,
                },
                Conditions=[
                    {"acl": "private"},
                    ["content-length-range", 1, 104857600],
                    ["starts-with", "$key", file_key],
                    {"Content-Type": file_mime_type},
                ],
                ExpiresIn=3600
            )
            file_url["uploadId"] = str(upload_id)
            file_url["type"]=file_mime_type
            file_urls.append(file_url)

        return file_urls

    def create_post(self, user_id, request_body,query_params):
        
        datetime_now = datetime.now()
        radius=db_client.Users.find_one({"_id":user_id},{"radius":1,"_id":0})

        N = 12        
        post_id = ''.join(random.choices(string.ascii_uppercase +string.ascii_lowercase+string.digits, k = N))

        commetbox=request_body.get("comments") or True

        if request_body.get("categoryId"):
            category=request_body.get("categoryId")
        else:
            category="" 

        result = db_client["Posts"].insert_one(
            {
                "createdBy": user_id,
                "createdOn": datetime_now,
                "updatedOn": datetime_now,
                "status": "ACTIVE",
                "commentBox":commetbox,
                "24hour_status":"PENDING",
                "post_id":post_id,
                "visibleTo": request_body["visibleTo"],  # list of valid user ids or public/private/loop
                "markedInappropriateReasons": [],
                "caption": request_body.get("caption"),
                "hashtags": request_body.get("hashtags"),
                "category": category,
                "radius":radius["radius"],
                "comments":0,
                "reactions":0,
                "location": {
                    "type": "Point",
                    "coordinates": [request_body["longitude"], request_body["latitude"]]
                }
            }
        )
        
        post_id = result.inserted_id

        insert_upload_data = [
            {
                "_id": ObjectId(_file["uploadId"]),
                "sequence": _file["sequence"],
                "type":_file["type"],
                "postId": post_id,
                "key": _file["name"],
                "createdBy": user_id,
                "createdOn": datetime.now(),
                "updatedOn": datetime.now(),              
                "status": "ACTIVE",
                "views": 0,
            }
            
            for _file in request_body["uploadData"]
        ]
        if insert_upload_data:
            db_client["PostUploads"].insert_many(insert_upload_data)

        hcl_data=[{
            "hashtags": request_body.get("hashtags"),
            "category": category,
            "radius":radius["radius"],
            "location": {
                "type": "Point",
                "coordinates": [request_body["longitude"], request_body["latitude"]]
            }   
        }]
        if hcl_data:
            db_client["HCL"].insert_many(hcl_data)
        
    def get_user_feed_posts(self, user_id, query_params):

        offset = query_params.get("offset") or 0
        limit = int(query_params.get("limit") or 20)
        max_distance = int(query_params.get("radius") or 20000)

        user_obj = db_client.Users.find_one({"_id": ObjectId(user_id)}) or {}
        exclude_user_ids = user_obj.get("blockedUserIds", []) + user_obj.get("blockedByUserIds", [])
        hidden_post_ids = [str(doc["_id"]) for doc in db_client.HidePosts.find({"userId": user_id, "status": "Hidden"})]
        blocked_post_ids = [str(doc["postId"]) for doc in db_client.BlockPosts.find({"userId": user_id, "status": "Blocked"})]

        empty_response = {
            "data": [],
            "nextPage": None
        }


        looped_user_ids = self.get_loop_user_ids(user_id)

        


        posts_query = None
        if query_params.get("userId"):
            # logic to get a particular profile's posts.

            if user_id == query_params["userId"]:
                # to get self profile.
                posts_query = {
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "createdBy": ObjectId(user_id)
                }
            
            else:
                if query_params["userId"] in exclude_user_ids:
                    # to return no posts in case user is blocked.
                    return empty_response
                
                user_obj = db_client.Users.find_one({"_id": ObjectId(query_params["userId"]),"status":"ACTIVE"})
                if user_obj["accessibility"] == "PRIVATE":
                    return empty_response

                posts_query = {
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "createdBy": ObjectId(query_params["userId"]),
                    "visibleTo": "PUBLIC"
                }

        elif query_params.get("status") and query_params["status"] == "APPROVAL_PENDING":
            # To fetch posts past the 24 hr limit which are to be approved.
            posts_query = {
                "status": query_params["status"],
                "24hour_status":{"$in": ["PENDING", "SAVED"]},
                "createdBy": ObjectId(user_id)
            }

        elif query_params.get("post_id"):
            # To fetch posts past the 24 hr limit which are to be approved.
            posts_query = {
                "post_id": query_params["post_id"],
                "24hour_status":{"$in": ["PENDING", "SAVED"]},
                "status": {"$in": ["ACTIVE", "SAVED"]}
            }
        
        elif query_params.get("longitude") and query_params.get("latitude") and query_params.get("loopPosts"):
            # To fetch Near as well as Loop posts.
            posts_query = {
                "status": "ACTIVE",
                "24hour_status":{"$in": ["PENDING", "SAVED"]},
                "visibleTo": "PUBLIC",
                "$or": [
                    {
                        "createdBy": {"$ne": ObjectId(user_id)},
                        "location": {
                            "$near": {
                                "$geometry": {
                                    "type": "Point",
                                    "coordinates": [
                                        float(query_params["longitude"]),
                                        float(query_params["latitude"])
                                    ]
                                },
                                "$maxDistance": max_distance,
                            }
                        }
                    }
                ]
            }

            loop_user_ids = self.get_loop_user_ids(user_id)
            if loop_user_ids:
                posts_query["$or"].append(
                    {
                        "createdBy": {"$in": loop_user_ids}
                    }
                )

        elif query_params.get("longitude") and query_params.get("latitude"):
            # To fetch posts within a certain radius
            posts_query = {
                "status": "ACTIVE",
                "24hour_status":{"$in": ["PENDING", "SAVED"]},
                "visibleTo": "PUBLIC",
                "createdBy": {"$ne": ObjectId(user_id)},
                "location": {
                    "$near": {
                        "$geometry": {
                            "type": "Point",
                            "coordinates": [
                                float(query_params["longitude"]),
                                float(query_params["latitude"])
                            ]
                        },
                        "$maxDistance": max_distance,
                    }
                }
            }
            
           
        elif query_params.get("hashtag"):
            # To fetch posts searched based on hashtag
            regx = regex.Regex(".*{search_term}.*".format(search_term=query_params["hashtag"]), re.IGNORECASE)
            posts_query = {
                "status": {"$in": ["ACTIVE", "SAVED"]},
                "24hour_status":{"$in": ["PENDING", "SAVED"]},
                "visibleTo": "PUBLIC",
                "createdBy": {"$ne": ObjectId(user_id)},
                "hashtags": {"$regex": regx}
            }

        elif query_params.get("category"):
            # To fetch posts searched based on category
            regx = regex.Regex(".*{search_term}.*".format(search_term=query_params["category"]), re.IGNORECASE)
            category_id=db_client.Categories.find({"category_name":{"$regex": regx}},{"_id":1})
            for i in category_id:
                posts_query = {
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "visibleTo": "PUBLIC",
                    "createdBy": {"$ne": ObjectId(user_id)},
                    "category": str(i["_id"])
                }
        elif query_params.get("categoryId"):
            categoryId = query_params.get("categoryId")
            posts_query={
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "visibleTo": "PUBLIC",
                    "createdBy": {"$ne": ObjectId(user_id)},
                    "category":categoryId
            }

        elif query_params.get("videos") and query_params.get("user_id"):
            post_id=[]
            query=db_client.PostUploads.find({"type":"audio/mpeg"})
            for id in query:
                post_id.append(id["postId"])
            
            posts_query={
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "_id":{"$in":post_id},
                    "visibleTo": "PUBLIC",
                    "createdBy": {"$ne": ObjectId(user_id)}
            }

        elif query_params.get("uploadId"):
            uploadId=query_params["uploadId"]
            print(uploadId)
            post_id=[]
            query=db_client.PostUploads.find({"_id":ObjectId(uploadId)})
            for id in query:
                post_id.append(id["postId"])                       
            posts_query={
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "_id":{"$in":post_id},
                    "visibleTo": "PUBLIC"
            }
        
        elif query_params.get("videos"):
            post_id=[]
            query=db_client.PostUploads.find({"type":"audio/mpeg"})
            for id in query:
                post_id.append(id["postId"])
            
            posts_query={
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "_id":{"$in":post_id},
                    "visibleTo": "PUBLIC"
            }

        elif query_params.get("bounce"): 
            randomUsers=[] 
            # Aggregation
            cursor = db_client.Users.aggregate([
                {"$match": {"user_type":{"$in": ["I", "C"]},"status":"ACTIVE"}}, # filter the results
                {"$sample": {"size": 20}}                                           # You want to get 5 docs
                ])            
            for document in cursor:
                randomUsers.append(document["_id"]) 

            posts_query={
                    "status": {"$in": ["ACTIVE", "SAVED"]},
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "createdBy": {"$in": randomUsers},
                    "visibleTo": "PUBLIC"
            }
            random_posts=db_client.posts.aggregate([{ "$sample": { "size": 10 } }])
                  
        elif query_params.get("loopPosts"):
            # To fetch Loop posts.
            loop_user_ids = self.get_loop_user_ids(user_id)

            if not loop_user_ids:
                return empty_response
            
            else:
                posts_query = {
                    "createdBy": {"$in": loop_user_ids},
                    "status": "ACTIVE",
                    "24hour_status":{"$in": ["PENDING", "SAVED"]},
                    "visibleTo": "PUBLIC",
                }                

        else:
            return empty_response

        projection = {
            "caption": 1,
            "comments": 1,
            "createdBy": 1,
            "createdOn": 1,
            "hashtags": 1,
            "category": 1,
            "reactions": 1,
            "updatedOn": 1,
        }

        
        posts = list(
            db_client["Posts"].find(posts_query, projection=projection).sort("createdOn", -1).skip(offset).limit(limit+1) # fetched an extra doc to power pagination logic
        ) or []

        next_page = None
        if len(posts) > limit:
            next_page = {"offset": offset + limit, "limit": limit}
            posts = posts[:-1]  # remove the extra doc fetched

        post_ids = [post["_id"] for post in posts]

        if post_ids:
            post_uploads = list(db_client["PostUploads"].find({"postId": {"$in": post_ids},"status": "ACTIVE"}).sort("sequence", 1))
            post_uploads_map = {}
            for upload in post_uploads:
                post_uploads_map.setdefault(str(upload["postId"]), []).append(upload)

            post_comments_aggregation = [
                {
                    "$match": {"postId": {"$in": post_ids}}
                },
                {
                    "$group": {
                        "_id": "$postId",
                        "comment": {"$last": "$comment"},
                        "commentType": {"$last": "$commentType"},
                        "commentedBy": {"$last": "$createdBy"},
                    }
                }
            ]
            post_comments = list(db_client.PostComments.aggregate(post_comments_aggregation)) or []
            post_comment_map = {
                str(comment["_id"]): comment
                for comment in post_comments
            }

            post_reactions_aggregation = [
                {
                    "$match": {"postId": {"$in": post_ids}}
                },
                {
                    "$group": {
                        "_id": "$postId",
                        "reactionTypes": {"$push": "$type"},
                    }
                }
            ]
            post_reactions = list(db_client.PostReactions.aggregate(post_reactions_aggregation)) or []
            post_most_common_reactions_map = {
                str(reaction["_id"]): Counter(reaction["reactionTypes"]).most_common(1)[0][0]
                for reaction in post_reactions
                if reaction.get("reactionTypes")
            }

            self_reactions = list(
                db_client.PostReactions.find(
                    {
                        "createdBy": ObjectId(user_id),
                        "postId": {"$in": post_ids}
                    }
                )
            )
            self_reaction_type_map = {
                str(reaction["postId"]): reaction["type"]
                for reaction in self_reactions
            }

        # ====================================================================================================
        # Fetch reactions by the logged-in user for the posts in the fetched list
        self_reactions = list(
            db_client.PostReactions.find(
                {
                    "createdBy": ObjectId(user_id),
                    "postId": {"$in": post_ids}
                }
            )
        )
        self_reaction_type_map = {
            str(reaction["postId"]): reaction["type"]
            for reaction in self_reactions
        }
        # ====================================================================================================

        # Fetch Looped User ids
        loop_user_ids = self.get_loop_user_ids(user_id)

        # print(f"Looped Usser Ids : {loop_user_ids}")

        for post in posts:
            post["id"] = str(post.pop("_id"))
            post["createdOn"] = int(post["createdOn"].timestamp() * 1000)
            post["updatedOn"] = int(post["updatedOn"].timestamp() * 1000)
            post["createdBy"] = str(post["createdBy"])

            # Check if the logged-in user has given a reaction to the post
            if self_reaction_type_map.get(post["id"]):
                post["selfReactionType"] = self_reaction_type_map[post["id"]]
            else:
                # If the user hasn't given any reaction, set the value to 0
                post["selfReactionType"] = 0

            loop_user_ids = [str(loop_user_id) for loop_user_id in loop_user_ids]

            # Check if the post's createdBy is in the loop_user_ids
            if post["createdBy"] in loop_user_ids:
                post["IsLoopedUserPost"] = True
            else:
                post["IsLoopedUserPost"] = False



            if post["category"] !="":
                category_id=ObjectId(post["category"])
                category=db_client.Categories.find_one({"_id":category_id},{"category_name":1,"key":1,"_id":0}) or {}              
            
                if category:
                    post["category"] = [{
                        "category_name": category["category_name"],
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{category.get('key')}",
                    }]
                                      
            else:
                post["category"]=[]          

            post["videos"] = [
                    {
                        "uploadId": str(upload["_id"]),
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{upload['key']}",
                        "views": upload.get("views"),
                        "type": upload.get("type")
                    }
                    for upload in post_uploads_map.get(post["id"], []) if upload.get("type") in ["audio/mpeg", "audio/mpeg4"]
                ]


            post["images"] = [
                    {
                                       
                        "uploadId": str(upload["_id"]),
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{upload['key']}",
                        "views": upload.get("views"),
                        "type": upload.get("type")
                    }
                    for upload in post_uploads_map.get(post["id"], []) if upload.get("type") in ["image/jpeg", "image/tiff", "image/gif", "image/png"]
                ]



            if post_comment_map.get(post["id"]):
                comment = post_comment_map[post["id"]]
                if comment.get("status") == "ACTIVE":
                    comment.pop("_id")
                    comment["commentedBy"] = str(comment["commentedBy"])
                    post["latestComment"] = [comment]
                else:
                    post["latestComment"] = []
            else:
                post["latestComment"] = []

            if self_reaction_type_map.get(post["id"]):
                post["selfReactionType"] = self_reaction_type_map[post["id"]]
            else:
                post["selfReactionType"] =""

            if post_most_common_reactions_map.get(post["id"]):
                post["mostCommonReactionType"] = post_most_common_reactions_map[post["id"]]
            else:
                post["mostCommonReactionType"]=""


        if query_params.get("videos") and query_params.get("userId") or query_params.get("videos"):    
           posts=[item for item in posts if item['videos'] != []]

        if query_params.get("post_id") and query_params.get("share"):
            link="https://tw8f454xlc.execute-api.us-east-1.amazonaws.com/dev/posts?post_id="+query_params["post_id"]
            posts={"link":link}

        response = {
            "data": posts,
            "nextPage": next_page
        }

        return response

    def get_loop_user_ids(self, user_id):
        loop_query = {
            "createdBy": ObjectId(user_id),
            "status": "ACCEPTED"
        }

        projection = {
            "_id": 0,
            "createdFor": 1,
        }

        loop_user_ids = (
            list(
                db_client.LoopRequests.aggregate(
                    [
                        {"$match": loop_query},
                        {"$project": projection},
                        {
                            "$group": {
                                "_id": None,
                                "userIds": {"$addToSet": "$createdFor"}
                            }
                        }
                    ]
                )
            ) or [{}]
        )[0].get("userIds", [])
        print("loop_user_ids:", loop_user_ids)
        return loop_user_ids

    def mark_inappropriate(self, user_id, post_id, request_body):
        db_client["Posts"].update_one(
            {
                "_id": ObjectId(post_id),
            },
            {
                "$addToSet": {
                    "markedInappropriateReasons": {
                        "createdBy": user_id,
                        "createdOn": datetime.now(),
                        "reason": request_body["reason"],
                    }
                }
            }
        )

    def change_status(self, user_id, post_id, new_status):

        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if self.is_post_active(query):
            db_client["Posts"].update_one(
                query,
                {
                    "$set": {
                        "status": new_status,
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "Post status updated."}
            response_code = 200
        
        else:
            response = {"message": "Only active post's status can be updated."}
            response_code = 400
        
        return response, response_code

    def edit_24hour_status(self, user_id, post_id, new_status):

        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if query:
            db_client["Posts"].update_one(
                query,
                {
                    "$set": {
                        "24hour_status": new_status,
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "Post 24hour_status updated."}
            response_code = 200
        
        else:
            response = {"message": "unable updated."}
            response_code = 400
        
        return response, response_code
    
    def edit_caption(self, user_id, post_id, caption):
        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if self.is_post_active(query):
            db_client["Posts"].update_one(
                query,
                {
                    "$set": {
                        "caption": caption,
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "Post caption updated."}
            response_code = 200
        
        else:
            response = {"message": "Only active post's caption can be updated."}
            response_code = 400
        
        return response, response_code

    def edit_visibleTo(self, user_id, post_id, visibleTo):
        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if self.is_post_active(query):
            db_client["Posts"].update_one(
                query,
                {
                    "$set": {
                        "visibleTo": visibleTo,
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "accessibility updated."}
            response_code = 200
        
        else:
            response = {"message": "Only active post's accessibility can be updated."}
            response_code = 400
        
        return response, response_code
    
    def edit_hashtags(self, user_id, post_id, hashtags):
        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if self.is_post_active(query):
            db_client["Posts"].update_one(
                query,
                {
                    "$set": {
                        "hashtags": hashtags,
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "hashtags updated."}
            response_code = 200
        
        else:
            response = {"message": "Only active post's hashtags can be updated."}
            response_code = 400
        
        return response, response_code
      
    def edit_category(self, user_id, post_id, categoryId):
        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if self.is_post_active(query):
            db_client["Posts"].update_one(
                query,
                {
                    "$set": {
                        "category": categoryId,
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "category updated."}
            response_code = 200
        
        else:
            response = {"message": "Only active post's category can be updated."}
            response_code = 400
        
        return response, response_code

    def delete_post(self, user_id, post_id):
        db_client["Posts"].update_one(
            {
                "_id": ObjectId(post_id),
                "createdBy": user_id,
            },
            {
                "$set": {
                    "status": "DELETED",
                    "deletedOn": datetime.now()
                }
            }
        )
    
    def delete_upload(self, user_id,post_id, upload_id):

        query = {
            "_id": ObjectId(post_id),
            "createdBy": user_id,
        }

        if self.is_post_active(query):
            db_client["PostUploads"].update_one(
                {
                    "_id":ObjectId(upload_id),
                    "createdBy": user_id,
                },
                {
                    "$set": {
                        "status": "INACTIVE",
                        "updatedOn": datetime.now()
                    }
                }
            )
            response = {"message": "upload deleted."}
            response_code = 200
        
        else:
            response = {"message": "Only active post's uploads can be updated."}
            response_code = 400
        
        return response, response_code
    
    def is_post_active(self, query):
        post = db_client["Posts"].find_one(query)
        return True if post and post["status"] == "ACTIVE" else False

    def add_upload_view(self, user_id, post_id, upload_id):   
        post_id = ObjectId(post_id)
        upload_id = ObjectId(upload_id)
        view_obj = {
            "createdBy": user_id,
            "postId": post_id,
            "uploadId": upload_id,
        }
        existing_view = db_client.PostUploadViews.find_one(view_obj)

        if existing_view:
            return

        view_obj["createdOn"] = datetime.now()
        db_client.PostUploadViews.insert_one(view_obj)
        db_client.PostUploads.update_one(
            {"_id": upload_id},
            {"$inc": {"views": 1}}
        )

    def get_video(self, user_id,query_params):
        offset = query_params.get("offset") or 0
        limit = int(query_params.get("limit") or 20)     
        if query_params.get("userId"):
            user_id1=ObjectId(query_params["userId"])
        else:
            user_id1 = ObjectId(user_id)

        posts_query={
            "createdBy": user_id1,
            "status":"ACTIVE",
            "visibleTo":"PUBLIC"
        }
        projection={
            "_id":1,
        }
        
        posts = list(
            db_client["Posts"].find(posts_query,projection=projection).sort("createdOn", -1).skip(offset).limit(limit+1) # fetched an extra doc to power pagination logic
        ) or []

        next_page = None
        if len(posts) > limit:
            next_page = {"offset": offset + limit, "limit": limit}
            posts = posts[:-1]  # remove the extra doc fetched

        post_ids = [post["_id"] for post in posts]

        if post_ids:
        # get_video = db_client.PostUploads.find(query,{"key":1,"_id":1,"type":1,"views":1})
            post_uploads = list(db_client["PostUploads"].find({"postId": {"$in": post_ids},"status": "ACTIVE"}).sort("sequence", 1))
            post_uploads_map = {}
            print(post_uploads)
            for upload in post_uploads:
                # print(upload)
                post_uploads_map.setdefault(str(upload["postId"]), []).append(upload)

        for post in posts:
            post["id"] = str(post.pop("_id"))
        
            post["images"] = [
                        {
                            "uploadId": str(upload["_id"]),
                            "url": f"https://{bucket_name}.s3.amazonaws.com/{upload['key']}",
                            "views": upload.get("views"),
                            "type": upload.get("type")
                        }
                        for upload in post_uploads_map.get(post["id"], []) 
                        #if upload.get("type")=="image/jpeg"
                    ]
            post["videos"] = [
                        {
                           
                            "uploadId": str(upload["_id"]),
                            "url": f"https://{bucket_name}.s3.amazonaws.com/{upload['key']}",
                            "views": upload.get("views"),
                            "type": upload.get("type")
                            
                        }
                        for upload in post_uploads_map.get(post["id"], []) 
                        #if upload.get("type")=="audio/mpeg"
                    ]
        
        response = {"data": posts,
                    "nextPage": next_page
                    }

        return response

    def get_post_by_id(self, _id):
        # try:
        #     converted_id = ObjectId(_id)
        #     post_obj = db_client["Posts"].find_one({"_id": converted_id}) or {}

        #     def convert_object_ids_to_strings(obj):
        #         if isinstance(obj, dict):
        #             for key, value in obj.items():
        #                 if isinstance(value, ObjectId):
        #                     obj[key] = str(value)
        #                 elif isinstance(value, dict):
        #                     convert_object_ids_to_strings(value)
        #         elif isinstance(obj, list):
        #             for i in range(len(obj)):
        #                 if isinstance(obj[i], ObjectId):
        #                     obj[i] = str(obj[i])
        #                 elif isinstance(obj[i], dict):
        #                     convert_object_ids_to_strings(obj[i])
            
        #     convert_object_ids_to_strings(post_obj)
            
        #     response = {"message": "Post Fetched Successfully", "post": post_obj,"statusCode":200}
        #     return response
        # except Exception as e:
        #     return {"error": str(e)}, 500



        converted_id = ObjectId(_id)
        posts_query = {
            "_id":converted_id,
            # "24hour_status":{"$in": ["PENDING", "SAVED"]},
            "status": {"$in": ["ACTIVE", "SAVED"]}
        }
        

        projection = {
            "caption": 1,
            "comments": 1,
            "createdBy": 1,
            "createdOn": 1,
            "hashtags": 1,
            "category": 1,
            "reactions": 1,
            "updatedOn": 1,
        }

        
        posts = list(
            db_client["Posts"].find(posts_query, projection=projection).sort("createdOn", -1)
        ) or []

        post_ids = [post["_id"] for post in posts]

        if post_ids:
            post_uploads = list(db_client["PostUploads"].find({"postId": {"$in": post_ids},"status": "ACTIVE"}).sort("sequence", 1))
            post_uploads_map = {}
            for upload in post_uploads:
                post_uploads_map.setdefault(str(upload["postId"]), []).append(upload)

            post_comments_aggregation = [
                {
                    "$match": {"postId": {"$in": post_ids}}
                },
                {
                    "$group": {
                        "_id": "$postId",
                        "comment": {"$last": "$comment"},
                        "commentType": {"$last": "$commentType"},
                        "commentedBy": {"$last": "$createdBy"},
                    }
                }
            ]
            post_comments = list(db_client.PostComments.aggregate(post_comments_aggregation)) or []
            post_comment_map = {
                str(comment["_id"]): comment
                for comment in post_comments
            }

            post_reactions_aggregation = [
                {
                    "$match": {"postId": {"$in": post_ids}}
                },
                {
                    "$group": {
                        "_id": "$postId",
                        "reactionTypes": {"$push": "$type"},
                    }
                }
            ]
            post_reactions = list(db_client.PostReactions.aggregate(post_reactions_aggregation)) or []
            post_most_common_reactions_map = {
                str(reaction["_id"]): Counter(reaction["reactionTypes"]).most_common(1)[0][0]
                for reaction in post_reactions
                if reaction.get("reactionTypes")
            }

        for post in posts:
            post["id"] = str(post.pop("_id"))
            post["createdOn"] = int(post["createdOn"].timestamp() * 1000)
            post["updatedOn"] = int(post["updatedOn"].timestamp() * 1000)
            post["createdBy"] = str(post["createdBy"])


            if post["category"] !="":
                category_id=ObjectId(post["category"])
                category=db_client.Categories.find_one({"_id":category_id},{"category_name":1,"key":1,"_id":0}) or {}              
            
                if category:
                    post["category"] = [{
                        "category_name": category["category_name"],
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{category.get('key')}",
                    }]

            
            if post["createdBy"] !="":
                createdBy=ObjectId(post["createdBy"])
                created_by_user=db_client.Users.find_one({"_id":createdBy}) or {}     

            
                if created_by_user:
                    post["createdBy"] = [{
                        "id": post["createdBy"],
                        "name":created_by_user["name"],
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{created_by_user.get('key')}",
                    }]
                                      
            else:
                post["category"]=[]          

            post["videos"] = [
                    {
                        "uploadId": str(upload["_id"]),
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{upload['key']}",
                        "views": upload.get("views"),
                        "type": upload.get("type")
                    }
                    for upload in post_uploads_map.get(post["id"], []) if upload.get("type") in ["audio/mpeg", "audio/mpeg4"]
                ]


            post["images"] = [
                    {
                                       
                        "uploadId": str(upload["_id"]),
                        "url": f"https://{bucket_name}.s3.amazonaws.com/{upload['key']}",
                        "views": upload.get("views"),
                        "type": upload.get("type")
                    }
                    for upload in post_uploads_map.get(post["id"], []) if upload.get("type") in ["image/jpeg", "image/tiff", "image/gif", "image/png"]
                ]



            if post_comment_map.get(post["id"]):
                comment = post_comment_map[post["id"]]
                if comment.get("status") == "ACTIVE":
                    comment.pop("_id")
                    comment["commentedBy"] = str(comment["commentedBy"])
                    post["latestComment"] = [comment]
                else:
                    post["latestComment"] = []
            else:
                post["latestComment"] = []


            if post_most_common_reactions_map.get(post["id"]):
                post["mostCommonReactionType"] = post_most_common_reactions_map[post["id"]]
            else:
                post["mostCommonReactionType"]=""



        response = {
            "data": posts,
        }

        return response





class PostActivityHandler:

    def get_post_comments(self, user_id, post_id, query_params):

        user_obj = db_client.Users.find_one({"_id": ObjectId(user_id)})
        exclude_user_ids = user_obj.get("blockedUserIds", []) + user_obj.get("blockedByUserIds", [])

        query = {
            "postId": ObjectId(post_id),
            "status": "ACTIVE"
        }

        if exclude_user_ids:
            query["createdBy"] = {"$nin": exclude_user_ids}

        projection = {
            "createdOn": 1,
            "createdBy": 1,
            "comment": 1,
            "commentType": 1,
            "replies":1
        }
        comments = list(db_client["PostComments"].find(query, projection=projection))

        for comment in comments:
            comment["id"] = str(comment.pop("_id"))
            comment["createdBy"] = str(comment["createdBy"])
            comment["createdOn"] = int(comment["createdOn"].timestamp() * 1000)

        response = {"data": comments}
        return response


    def add_comment(self, user_id, post_id, comment, comment_type):
        time_now = datetime.now()
        db_client["PostComments"].insert_one(
            {
                "createdBy": user_id,
                "createdOn": time_now,
                "updatedOn": time_now,
                "postId": ObjectId(post_id),
                "status": "ACTIVE",
                "comment": comment,
                "commentType": comment_type,
            }
        )
        msg = db_client.NotificationContent.find_one({"_id": ObjectId("61c48d8eaf2d65aa18e5c5d5")}, {"_id": 0, "msg": 1})

        post_user = db_client.Posts.find_one({"_id": ObjectId(post_id)}, {"_id": 1, "createdBy": 1, "status": 1})

        # Get the user ID and name of the person adding the comment
        sender = db_client.Users.find_one({"_id": ObjectId(user_id)}, {"_id": 1, "name": 1, "status": 1})

        # Get the profile image of the user who posted the post
        # post_user_profile = db_client.Users.find_one({"_id": ObjectId(post_user["createdBy"])}, {"_id": 1, "key": 1, "status": 1})

        # Get the profile image of the user who added the comment
        comment_user_profile = db_client.Users.find_one({"_id": ObjectId(user_id)}, {"_id": 1, "key": 1, "status": 1})

        # Insert the notification into the Notifications collection
        db_client.Notifications.insert_one({
            "status": "UNREAD",
            "receiverId": post_user["createdBy"],
            "notification": msg["msg"],
            "type": "comment",
            "createdOn": datetime.now(),
            "senderId": user_id,
            "senderName": sender["name"],  # Add sender's name
            "key": comment_user_profile["key"],
            "reactionType": None
        })

        db_client["Posts"].update_one(
            {
                "_id": ObjectId(post_id)
            },
            {
                "$inc": {"comments": 1}
            }
        )

    def update_comment(self, user_id, post_id, comment, comment_type,query_params):
        commentId=query_params.get("commentId")
        query = {
            "postId": ObjectId(post_id),
            "createdBy": user_id,
            "_id":ObjectId(commentId),
            "status": "ACTIVE"
        }
        
        db_client["PostComments"].update_one(
            query,
            {
                "$set": {
                    "comment": comment,
                    "commentType": comment_type,
                    "updatedOn": datetime.now()
                }
            }
        )   
        

    def remove_comment(self, user_id, post_id, comment_id):

        user=db_client.Posts.find_one({"_id":ObjectId(post_id)},{"createdBy":1}) or {}
        
        if user.get("createdBy")== user_id:
            print("sucess")
            db_client["PostComments"].update_one(
            {
                "_id": ObjectId(comment_id),
                "postId": ObjectId(post_id),
                "status": "ACTIVE"
            },
            {
                "$set": {
                    "status": "INACTIVE",
                    "updatedOn": datetime.now(),
                }
            }
            )
            db_client["Posts"].update_one(
                {
                    "_id": ObjectId(post_id)
                },
                {
                    "$inc": {"comments": -1}
                }
            )


        # if user_id==user:
        else:
            db_client["PostComments"].update_one(
                {
                    "_id": ObjectId(comment_id),
                    "postId": ObjectId(post_id),
                    "createdBy": user_id,
                    "status": "ACTIVE"
                },
                {
                    "$set": {
                        "status": "INACTIVE",
                        "updatedOn": datetime.now(),
                    }
                }
            )
            db_client["Posts"].update_one(
                {
                    "_id": ObjectId(post_id)
                },
                {
                    "$inc": {"comments": -1}
                }
            )
    
    def get_comment_reply(self, user_id, comment_id):

        user_obj = db_client.Users.find_one({"_id": ObjectId(user_id)})
        exclude_user_ids = user_obj.get("blockedUserIds", []) + user_obj.get("blockedByUserIds", [])

        query = {
            "commentId": ObjectId(comment_id),
            "status": "ACTIVE"
        }

        if exclude_user_ids:
            query["createdBy"] = {"$nin": exclude_user_ids}

        projection = {
            "createdOn": 1,
            "createdBy": 1,
            "reply": 1,
            "replyType": 1,
        }
        replies = list(db_client["PostCommentReplies"].find(query, projection=projection))

        for reply in replies:
            reply["id"] = str(reply.pop("_id"))
            reply["createdBy"] = str(reply["createdBy"])
            reply["createdOn"] = int(reply["createdOn"].timestamp() * 1000)

        response = {"data": replies}
        return response


    def add_comment_reply(self, user_id, comment_id, reply, reply_type):
        time_now = datetime.now()
        db_client["PostCommentReplies"].insert_one(
            {
                "createdBy": user_id,
                "createdOn": time_now,
                "updatedOn": time_now,
                "commentId": ObjectId(comment_id),
                "status": "ACTIVE",
                "reply": reply,
                "replyType": reply_type,
            }
        )
        comment = db_client.PostComments.find_one({"_id": ObjectId(comment_id)}, {"_id": 0, "createdBy": 1})
        msg = db_client.NotificationContent.find_one({"_id": ObjectId("61c48db3af2d65aa18e5c5d6")}, {"_id": 0, "msg": 1})

        if comment is not None:
            user = db_client.Users.find_one({"_id": ObjectId(comment["createdBy"])}, {"_id": 0, "name": 1, "key": 1})

            if user is not None:
                sender_id = user_id
                receiver_id = comment["createdBy"]

                db_client.Notifications.insert_one({
                    "status": "UNREAD",
                    "receiverId": receiver_id,
                    "notification": msg["msg"],
                    "type": "comment",
                    "createdOn": datetime.now(),
                    "senderId": sender_id,
                    "senderName": user["name"],  # Add sender's name
                    "key": user["key"],
                    "reactionType": None
                })
        db_client["PostComments"].update_one(
            {
                "_id": ObjectId(comment_id)
            },
            {
                "$inc": {"replies": 1}
            }
        )  

    def update_comment_reply(self, user_id, comment_id, reply, replyType,query_params):
        replyId=query_params.get("replyId")
        time_now = datetime.now()               
        db_client["PostCommentReplies"].update_one(
            {   
                "_id":ObjectId(replyId),
                "commentId": ObjectId(comment_id),
                "createdBy": user_id,
                "status": "ACTIVE", 
            },
            {
                "$set": {
                    "reply": reply,
                    "replyType": replyType,
                    "updatedOn": time_now
                }
            }
        )  
    
    def remove_comment_reply(self, user_id, comment_id, reply_id):
        post=db_client.PostComments.find_one({"_id":ObjectId(comment_id)},{"postId":1,"_id":0})
        post_id=post.get("postId")
        user=db_client.Posts.find_one({"_id":ObjectId(post_id)},{"createdBy":1})
        
        if user.get("createdBy")== user_id:
            db_client["PostCommentReplies"].update_one(
                {
                    "_id": ObjectId(reply_id),
                    "commentId": ObjectId(comment_id),
                    "status": "ACTIVE",
                },
                {
                    "$set": {
                        "status": "INACTIVE",
                        "updatedOn": datetime.now(),
                    }
                }
            )
            db_client["PostComments"].update_one(
                {
                    "_id": ObjectId(comment_id)
                },
                {
                    "$inc": {"replies": -1}
                }
            )

        else:
            db_client["PostCommentReplies"].update_one(
                {
                    "_id": ObjectId(reply_id),
                    "commentId": ObjectId(comment_id),
                    "createdBy": user_id,
                    "status": "ACTIVE",
                },
                {
                    "$set": {
                        "status": "INACTIVE",
                        "updatedOn": datetime.now(),
                    }
                }
            )
            db_client["PostComments"].update_one(
                {
                    "_id": ObjectId(comment_id)
                },
                {
                    "$inc": {"replies": -1}
                }
            )

    def get_loop_user_ids(self, user_id):
        loop_query = {
            "createdBy": ObjectId(user_id),
            "status": "ACCEPTED"
        }

        projection = {
            "_id": 0,
            "createdFor": 1,
        }

        loop_user_ids = (
            list(
                db_client.LoopRequests.aggregate(
                    [
                        {"$match": loop_query},
                        {"$project": projection},
                        {
                            "$group": {
                                "_id": None,
                                "userIds": {"$addToSet": "$createdFor"}
                            }
                        }
                    ]
                )
            ) or [{}]
        )[0].get("userIds", [])
        print("loop_user_ids:", loop_user_ids)
        return loop_user_ids

    def get_post_reactions(self, user_id, post_id, query_params):
        user_obj = db_client.Users.find_one({"_id": ObjectId(user_id)})
        if user_obj:
            exclude_user_ids = user_obj.get("blockedUserIds", []) + user_obj.get("blockedByUserIds", [])

            query = {
                "postId": ObjectId(post_id),
                "status": "ACTIVE"
            }

            if exclude_user_ids:
                query["createdBy"] = {"$nin": exclude_user_ids}

            projection = {
                "createdOn": 1,
                "createdBy": 1,
                "type": 1,
            }

            reactions = list(db_client["PostReactions"].find(query, projection=projection)) or []

            # Initialize a dictionary to count reactions by type
            reaction_counts = {}

            loop_user_ids = self.get_loop_user_ids(user_id)

            for reaction in reactions:
                reaction["_id"] = str(reaction.pop("_id"))
                reaction["createdBy"] = str(reaction["createdBy"])
                reaction["createdOn"] = int(reaction["createdOn"].timestamp() * 1000)

                # Check if createdBy is a looped user and set IsLoopedUser accordingly
                reaction["IsLoopedUser"] = str(reaction["createdBy"]) in loop_user_ids

                # Count reactions by type
                reaction_type = reaction["type"]
                reaction_counts[reaction_type] = reaction_counts.get(reaction_type, 0) + 1

            # Convert the reaction_counts dictionary into a list of dictionaries
            formatted_reaction_counts = [{"type": key, "count": value} for key, value in reaction_counts.items()]

            response_data = {
                "data": {
                    "all_reactions": reactions,
                    "react_counts": formatted_reaction_counts,
                    "message":"reactions retrived scuccesfully"
                }
            }
        else:
            response_data = {
                "message": "User not found",
                "statusCode": 404
            }
        
        
        return response_data


    def add_reaction(self, user_id, post_id, data):
        time_now = datetime.now()

        # Insert the reaction into the PostReactions collection
        db_client["PostReactions"].insert_one(
            {
                "createdBy": user_id,
                "createdOn": time_now,
                "updatedOn": time_now,
                "postId": ObjectId(post_id),
                "type": data["reactionType"],
                "status": "ACTIVE"
            }
        )

        # Get the user ID of the person who posted the post
        post_user = db_client.Posts.find_one({"_id": ObjectId(post_id)}, {"_id": 0, "createdBy": 1})

        msg = db_client.NotificationContent.find_one({"_id": ObjectId("61c48dcdaf2d65aa18e5c5d7")}, {"_id": 0, "msg": 1})

        user = db_client.Users.find_one({"_id": ObjectId(post_user["createdBy"])}, {"_id": 0, "name": 1, "key": 1})

        # Sender ID as the user who reacted to the post
        sender_id = user_id

        # Prepare the receiver ID as the user who posted the post
        receiver_id = post_user["createdBy"]

        # Get the specific reaction sent by the sender
        reaction_type = data["reactionType"]

        # Insert the notification into the Notifications collection
        db_client.Notifications.insert_one({
            "status": "UNREAD",
            "receiverId": receiver_id,
            "senderId": sender_id,
            "senderName": user["name"],  #  sender's name
            "notification": msg["msg"],
            "type": "reactions",
            "key": user["key"],
            "createdOn": datetime.now(),
            "reactionType": reaction_type
        })

        db_client["Posts"].update_one(
            {
                "_id": ObjectId(post_id)
            },
            {
                "$inc": {"reactions": 1}
            }
        )

    def update_reaction(self, user_id, post_id, reactionType):
        time_now = datetime.now()
        query = {
            "createdBy": user_id,
            "postId": ObjectId(post_id),
            "status": "ACTIVE"
        }

        result = db_client["PostReactions"].update_one(query,
            {
                "$set": {
                    "updatedOn": time_now,
                    "type": reactionType,                   
                }
            }
        )

        if result.matched_count == 0:
            print("No reaction found")
        else:
            print("Reaction updated successfully")

    def remove_reaction(self, user_id, post_id):

        updated = db_client["PostReactions"].update_one(
            {
                "postId": ObjectId(post_id),
                "createdBy": user_id,
                "status": "ACTIVE"
            },
            {
                "$set": {
                    "status": "INACTIVE",
                    "updatedOn": datetime.now(),
                }
            }
        )

        if updated:
            db_client["Posts"].update_one(
                {
                    "_id": ObjectId(post_id)
                },
                {
                    "$inc": {"reactions": -1}
                }
            )





    

