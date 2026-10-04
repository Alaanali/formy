from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Turn domain errors into 400s instead of 500s."""
    if isinstance(exc, ProtectedError):
        # on_delete=PROTECT: deleting a version with responses would destroy
        # the schema those answers need in order to mean anything.
        return Response(
            {
                "errors": {
                    "__all__": [
                        "Cannot delete: responses have been collected against this. "
                        "Archive it instead."
                    ]
                }
            },
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, IntegrityError):
        # Safety net: DRF builds uniqueness validators from
        # Meta.unique_together only, never from Meta.constraints, so a
        # constraint nobody mirrored would reach the client as a 500.
        return Response(
            {"errors": {"__all__": ["This conflicts with existing data."]}},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, DjangoValidationError):
        return Response({"errors": {"__all__": exc.messages}}, status=status.HTTP_400_BAD_REQUEST)

    return drf_exception_handler(exc, context)


class HasCapability(BasePermission):
    """Checks a capability against the object a view says governs it.

    Paired with queryset scoping, which decides what *exists* for a user: an
    invisible survey 404s rather than 403s, because a 403 would confirm the
    id is real. This class decides what may be done with what is visible.
    """

    message = "You do not have permission to perform this action on this survey."

    def has_permission(self, request, view):
        target = view.permission_object()
        if target is None:
            # A collection the queryset already scopes.
            return True
        return request.user.has_perm(view.required_perm(), target)

    def has_object_permission(self, request, view, obj):
        return request.user.has_perm(view.required_perm(), obj)


class CapabilityScopedMixin:
    """Maps HTTP method to capability, and names the governing object."""

    permission_classes = [IsAuthenticated, HasCapability]
    read_perm = None
    write_perm = None

    def required_perm(self):
        return self.read_perm if self.request.method in SAFE_METHODS else self.write_perm

    def permission_object(self):
        """The object a capability is checked against before an instance
        exists -- a parent for create, None for a scoped collection."""
        return None
