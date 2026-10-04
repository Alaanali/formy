from rest_framework.permissions import BasePermission

RESUME_TOKEN_HEADER = "X-Resume-Token"


class HasValidResumeToken(BasePermission):
    """Authenticates a respondent by bearer token rather than by account.

    Respondents are anonymous -- no auth record is created for them -- so the
    token is the whole of the authorization story for a draft. It travels in
    a header rather than the URL: a credential in a path shows up in access
    logs, proxy logs and Referer headers.

    Comparison is constant-time, and an expired or completed submission is
    rejected here rather than deeper in the view.
    """

    message = "A valid resume token is required for this submission."

    def has_object_permission(self, request, view, obj):
        import hmac

        presented = request.headers.get(RESUME_TOKEN_HEADER, "")
        if not presented or not obj.resume_token:
            return False
        if not hmac.compare_digest(presented, obj.resume_token):
            return False
        return obj.is_resumable
