from django.urls import path

from expenses.views import (
    expense_action_api, expense_api, expense_compare_api, expense_history_api, expense_photos_api, expense_state_api,
    expenses_api, expenses_view, photo_view,
)

app_name = 'expenses'

urlpatterns = [
    path('expenses/', expenses_view, name='expenses'),
    path('expenses/photos/<int:photo_id>/', photo_view, name='photo'),

    # API
    path('api/expenses/', expenses_api, name='expenses-api'),
    path('api/expenses/<int:expense_id>/', expense_api, name='expense-api'),
    path('api/expenses/<int:expense_id>/action/', expense_action_api, name='expense-action-api'),
    path('api/expenses/<int:expense_id>/photos/', expense_photos_api, name='expense-photos-api'),
    path('api/expenses/<int:expense_id>/history/', expense_history_api, name='expense-history-api'),
    path('api/expenses/<int:expense_id>/history/state/', expense_state_api, name='expense-state-api'),
    path('api/expenses/<int:expense_id>/history/compare/', expense_compare_api, name='expense-compare-api'),
]
