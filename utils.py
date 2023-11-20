import json

from bson import ObjectId
from functools import wraps

from settings import bucket_name, db_client, s3_client

def add_user_info(method):

    @wraps(method)
    def inner(request, *args, **kwargs):
        def find_user_ids(res):
            """Recursively finds fields which has user_ids

            Args:
            res: Input dict or list
            """
            nonlocal user_ids, user_keys
            if type(res) is list:
                for each_value in res:
                    find_user_ids(each_value)
            elif type(res) is dict:
                for k, v in res.items():
                    if k in user_keys:
                        if isinstance(v, list):
                            user_ids.extend(v)
                        elif isinstance(v, str):
                            user_ids.append(v)
                    elif type(v) in [list, dict]:
                        find_user_ids(v)
            user_ids = list(
                set([user_id for user_id in user_ids if isinstance(user_id, str)])
            )

        def replace_with_user_info(res):
            """Recursively replace fields which has user_ids with user info

            Args:
            res: Input dict or list
            """
            nonlocal user_ids, user_keys, user_info
            if type(res) is list:
                for each_v in res:
                    replace_with_user_info(each_v)
            elif type(res) is dict:
                for k, v in res.items():
                    if k in user_keys:
                        if isinstance(v, list):
                            for _i, _user_id in enumerate(v):
                                if isinstance(_user_id, str):
                                    res[k][_i] = user_info.get(_user_id)
                        elif isinstance(v, str):
                            res[k] = user_info.get(v)
                    elif type(v) in [list, dict]:
                        replace_with_user_info(v)

        # default user_id keys
        user_keys = [
            "createdBy",
            "commentedBy",
            "updatedBy",
            "reportedBy"
        ]

        # calls original method
        res = method(request, *args, **kwargs)
        content = json.loads(res.data)
        # find unique user_ids in response
        user_ids = []
        find_user_ids(content)
        user_info = list(
            db_client.Users.find(
                {
                    "_id": {"$in": list(map(ObjectId, user_ids))}
                }
            )
        )
        user_info = {
            str(user["_id"]): {
                "id":str(user["_id"]),
                "name": user["name"],
                "profile_url": s3_client.generate_presigned_url(
                            "get_object",
                            Params={
                                "Bucket": bucket_name,
                                "Key": user["key"],
                            },
                            ExpiresIn=3600
                        )
            }
            for user in user_info
        }

        # Update response with user info
        replace_with_user_info(content)
        res.data = json.dumps(content)
        return res

    return inner
