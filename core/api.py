from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
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
