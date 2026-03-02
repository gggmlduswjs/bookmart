from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.role not in roles:
                messages.error(request, '접근 권한이 없습니다.')
                return redirect('home')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
