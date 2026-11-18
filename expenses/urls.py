from django.urls import path

from expenses.views import (
    expense_action_api, expense_api, expense_photos_api, expenses_api, expenses_view, photo_view,
)

app_name = 'expenses'

urlpatterns = [
    path('expenses/', expenses_view, name='expenses'),
    path('expenses/add/', expenses_view, {'screen': 'add'}, name='expense-add'),
    path('expenses/<int:expense_id>/', expenses_view, name='expense'),
    path('expenses/photos/<int:photo_id>/', photo_view, name='photo'),

    # API
    path('api/expenses/', expenses_api, name='expenses-api'),
    path('api/expenses/<int:expense_id>/', expense_api, name='expense-api'),
    path('api/expenses/<int:expense_id>/action/', expense_action_api, name='expense-action-api'),
    path('api/expenses/<int:expense_id>/photos/', expense_photos_api, name='expense-photos-api'),
]
