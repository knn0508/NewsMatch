from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name="User")
    telegram_chat_id = models.BigIntegerField(unique=True, null=True, blank=True, verbose_name="Telegram Chat ID")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.telegram_chat_id}"


class Keyword(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="User")
    keyword_name = models.CharField(max_length=255, verbose_name="Keyword Name", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'keyword_name')
        indexes = [
            models.Index(fields=['user', 'keyword_name']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.keyword_name}"


class Article(models.Model):
    title = models.CharField(max_length=255, verbose_name="Title", db_index=True)   
    content = models.TextField(verbose_name="Content")       
    url = models.URLField(unique=True, verbose_name="URL")
    image_url = models.URLField(verbose_name="Image URL", null=True, blank=True)
    date = models.CharField(max_length=100, verbose_name="Date")

    class Meta:
        indexes = [
            models.Index(fields=['url']),
        ]

    def __str__(self):
        return self.title


class KeywordArticleMatch(models.Model):
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name="keyword_article_matches", verbose_name="Keyword")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="keyword_matches", verbose_name="Article")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('keyword', 'article')
        indexes = [
            models.Index(fields=['keyword', 'article']),
        ]

    def __str__(self):
        return f"{self.keyword} - {self.article}"

    
class Notification(models.Model):
    NOTIFICATION_STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('read', 'Read'),
        ('archived', 'Archived'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="User")
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, verbose_name="Keyword")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, verbose_name="Article")
    status = models.CharField(
        max_length=10,
        choices=NOTIFICATION_STATUS_CHOICES,
        default='unread',
        verbose_name="Status"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'keyword', 'article')
        indexes = [
            models.Index(fields=['user', 'status', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"Notification for {self.user.username} - {self.article.title}"