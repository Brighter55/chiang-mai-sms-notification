from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .models import OptInSubscriber
from .serializers import OptInSubscriberSerializer


class OptInCreateView(generics.CreateAPIView):
    """POST /api/opt-in/ — store a phone number with SMS consent."""

    queryset = OptInSubscriber.objects.all()
    serializer_class = OptInSubscriberSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"message": "You're in! Thanks for subscribing."},
            status=status.HTTP_201_CREATED,
        )
