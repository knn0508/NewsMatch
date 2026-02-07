from django.contrib import admin
from .models import Keyword, Article, KeywordArticleMatch, Notification, UserKeywordMatch, UserKeywordMatch



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

@admin.register(UserKeywordMatch)
class UserKeywordMatchAdmin(admin.ModelAdmin):
    list_display = ['user', 'keyword', 'created_at']
    list_filter = ['user']
    search_fields = ['keyword__keyword_name']