from django.urls import path
from expenses.views import (
    closed_expenses_api, expense_api, expense_photos_api, expense_reimburse_api, expense_review_api, expenses_api,
    expenses_view, guide_seen_api, my_closed_expenses_api, my_expenses_api,
    ignored_word_api, ignored_words_api, photo_view,
)

app_name = 'expenses'

urlpatterns = [
    path('expenses/', expenses_view, name='expenses'),
    path('expenses/photos/<int:photo_id>/', photo_view, name='photo'),

    # API
    path('api/expenses/', expenses_api, name='expenses-api'),
    path('api/expenses/closed/', closed_expenses_api, name='closed-expenses-api'),
    path('api/expenses/mine/', my_expenses_api, name='my-expenses-api'),
    path('api/expenses/guide/', guide_seen_api, name='guide-seen-api'),
    path('api/expenses/mine/closed/', my_closed_expenses_api, name='my-closed-expenses-api'),
    path('api/expenses/<int:expense_id>/', expense_api, name='expense-api'),
    path('api/expenses/<int:expense_id>/photos/', expense_photos_api, name='expense-photos-api'),
    path('api/expenses/<int:expense_id>/review/', expense_review_api, name='expense-review-api'),
    path('api/expenses/<int:expense_id>/reimburse/', expense_reimburse_api, name='expense-reimburse-api'),
    path('api/expenses/ignored-words/', ignored_words_api, name='ignored-words-api'),
    path('api/expenses/ignored-words/<int:word_id>/', ignored_word_api, name='ignored-word-api'),
]
