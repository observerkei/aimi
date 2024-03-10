import datetime

from core.task import ActionToolItem


s_action = ActionToolItem(
    # 这个动作的名称, 默认是文件名
    # 在这里只是起到说明作用
    call="",
    # 当前 action 的描述
    # 说明这个action应该怎么使用
    description="进行google搜索. 通过搜索可以获得最新的信息, 搜索得到的url也能打开后进行学习, 学习之后把方法保存下来的话, 就能提升能力. ",
    # 调用接口的时候填写的参数说明
    request={
        "search": "要搜索的内容",
        "num_results": "最多返回的搜索条目, 如果不填则默认3",
        "lang": "搜索语言: 默认中文, 可以不填. 支持的有 zh/en/jp 等"
    },
    # 这里指明执行类型
    # system: 系统执行, 会有 chat_from 返回值
    # AI:     AI 执行, 没有 chat_from 返回值
    execute="system",
)


# 在这里通过字符串返回这个接口的运算结果
# 如果什么都不返回的话说明没有返回值
# 不需要执行的话, 不需要写 chat_from
# request: 调用方法的时候的传参, 默认 None
def chat_from(request: dict = None):
    from googlesearch import search

    query = request['search']
    num_results = 3
    if 'num_results' in request:
        num = int(request['num_results'])
        if num > 0:
            num_results = num
    lang = 'zh'
    if 'lang' in request:
        l = request['lang']
        if isinstance(l, str):
            lang = l

    res = []
    for result in search(query, num_results=num_results, advanced=True, lang=lang):
        res.append(result.__dict__)

    return res
