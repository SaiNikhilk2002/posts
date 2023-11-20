from flask import Blueprint

from views import AddUploadViews, GetSignedUrlsView, ManagePostsView, ManagePostView, ManagePostComments, ManagePostReactions, ManageCommentsReply,FileUploadView, PostDeeplinkingView ,getVideoView,ManagePendingPosts,ManageRandomPosts,ManageTrendingHash,HidePostView,UnHidePostView,BlockPostView,UnblockPostView,RadiusSettingView
posts_blueprint = Blueprint("posts", __name__, url_prefix="/posts")

posts_blueprint.add_url_rule(
    "",
    view_func=ManagePostsView.as_view("manage_posts"),
    methods=["GET", "POST"],
)

posts_blueprint.add_url_rule(
    "/get-signed-urls",
    view_func=GetSignedUrlsView.as_view("get_signed_urls"),
    methods=["GET"],
)

posts_blueprint.add_url_rule(
   "/videos",
    view_func=getVideoView.as_view("getVideoView"),
    methods=["GET"] 
)

posts_blueprint.add_url_rule(
   "/file_upload",
    view_func=FileUploadView.as_view("s3_file_upload"),
    methods=["POST"] 
)

posts_blueprint.add_url_rule(
    "/<post_id>",
    view_func=ManagePostView.as_view("update_post"),
    methods=["PATCH", "DELETE"],
)

posts_blueprint.add_url_rule(
    "/<post_id>/comments",
    view_func=ManagePostComments.as_view("manage-post-comments"),
    methods=["GET", "POST", "PATCH", "DELETE"],
)

posts_blueprint.add_url_rule(
    "/<comment_id>/reply",
    view_func=ManageCommentsReply.as_view("manage-commnet-reply"),
    methods=["GET", "POST", "PATCH", "DELETE"],
)

posts_blueprint.add_url_rule(
    "/<post_id>/reactions",
    view_func=ManagePostReactions.as_view("manage-post-reactions"),
    methods=["GET", "POST", "PATCH", "DELETE"],
)

posts_blueprint.add_url_rule(
    "/<post_id>/uploads/<upload_id>/views",
    view_func=AddUploadViews.as_view("add-upload-views"),
    methods=["POST"],
)
posts_blueprint.add_url_rule(
    "/pending_posts",
    view_func=ManagePendingPosts.as_view("manage-pending-posts"),
    methods=["GET", "POST", "PATCH", "DELETE"],
)
posts_blueprint.add_url_rule(
    "/random_uploads",
    view_func=ManageRandomPosts.as_view("manage-random-posts"),
    methods=["GET", "POST", "PATCH", "DELETE"],
)
posts_blueprint.add_url_rule(
    "/trending_hashtag",
    view_func=ManageTrendingHash.as_view("manage-trending-hash"),
    methods=["GET", "POST"],
)
posts_blueprint.add_url_rule(
    "/<post_id>/hide",
    view_func=HidePostView.as_view("hide_post"),
    methods=["POST"],
)
posts_blueprint.add_url_rule(
    "/<post_id>/unhide",
    view_func=UnHidePostView.as_view("unhide_post"),
    methods=["POST"],
)
posts_blueprint.add_url_rule(
    "/<post_id>/block",
    view_func=BlockPostView.as_view('block_post'),
    methods=["POST"],
)
posts_blueprint.add_url_rule(
    "/<post_id>/unblock",
    view_func=UnblockPostView.as_view("unblock_post"),
    methods=["POST"],
)
posts_blueprint.add_url_rule(
    "/radius",
    view_func=RadiusSettingView.as_view("RadiusSetting"),
    methods=["POST","GET"],
)
posts_blueprint.add_url_rule(
    "/post_deep_linking",
    view_func=PostDeeplinkingView.as_view("PostDeeplinkingView"),
    methods=["GET"]
)