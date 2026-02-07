from django.contrib import admin
from .models import UserProfile, Keyword, Article, KeywordArticleMatch, Notification


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_chat_id', 'created_at', 'updated_at']
    search_fields = ['user__username', 'telegram_chat_id']
    list_filter = ['created_at']


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ['user', 'keyword_name', 'created_at']
    list_filter = ['user']
    search_fields = ['keyword_name']


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'url', 'date', 'image_url', 'short_content']
    search_fields = ['title', 'content']

    def short_content(self, obj):
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    short_content.short_description = 'Content'


@admin.register(KeywordArticleMatch)
class KeywordArticleMatchAdmin(admin.ModelAdmin):
    list_display = ['keyword', 'article', 'created_at']
    list_filter = ['keyword__user']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'keyword', 'article', 'status', 'created_at']
    list_filter = ['status', 'user']
    search_fields = ['article__title', 'keyword__keyword_name']