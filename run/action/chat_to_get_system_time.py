import datetime

from core.task import ActionToolItem


s_action = ActionToolItem(
    # 这个动作的名称, 默认是文件名
    # 在这里只是起到说明作用
    call="",
    # 当前 action 的描述
    # 说明这个action应该怎么使用
    description="获取当前系统时间: 时间是准确的.",
    # 调用接口的时候填写的参数说明
    request=None,
    # 这里指明执行类型
    # system: 系统执行, 会有 chat_from 返回值
    # AI:     AI 执行, 没有 chat_from 返回值
    execute="system",
)


# 在这里通过打印返回这个接口的运算结果
# 如果什么都不打印的话说明没有返回值
# 不需要执行的话, 不需要写 chat_from
def chat_from():
    def get_current_time():
        now = datetime.datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")

    return get_current_time()
