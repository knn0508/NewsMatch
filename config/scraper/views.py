from django.shortcuts import render

# Views not needed — all management is done via Django admin panel.

def get_article(request, article_id: int):
    """Get a single article by ID."""
    return get_object_or_404(Article, id=article_id)