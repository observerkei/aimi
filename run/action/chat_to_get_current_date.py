
from core.task import ActionToolItem


s_action = ActionToolItem(
    call="",
    description="获取当前日期",
    request="{}",
    execute="system",
)


def chat_from(request: dict = None):
    def get_current_date():
        import datetime
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        return current_date
    
    return get_current_date()

