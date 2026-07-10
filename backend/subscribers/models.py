from django.db import models


class OptInSubscriber(models.Model):
    phone = models.CharField(
        max_length=16,
        unique=True,
        db_index=True,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.phone
