"""时间工具：所有 ORM 列均为 naive UTC（SQLite func.now() 的存储格式），
统一从这里取"当前 UTC 时间"，不要直接用已弃用的 datetime.utcnow()。
【P1-3 修复】配套：API 序列化层（schemas.UtcDateTime）会给 naive datetime 补 UTC 时区标记，
前端 new Date() 才能正确转换为本地时间（否则北京时间显示早 8 小时）。
"""
import os
from datetime import date, datetime, timezone

#: 本地演示用的「假今天」。
#:
#: 结算系统每月只在 8、9 号开放结算入口 —— 也就是说，除了每月那两天，
#: 其余时间**根本跑不通完整链路**，本地演示和自动化实测都会卡在这。
#:
#: 设这个环境变量就能把「今天」钉死到某一天，用来演示与测试：
#:     SETTLE_FAKE_TODAY=2026-11-08
#:
#: 留空 = 用真实日期。**生产部署不要设这个变量**。
FAKE_TODAY_ENV = "SETTLE_FAKE_TODAY"


def utcnow() -> datetime:
    """当前 UTC 时间（naive，与 SQLite func.now() 的存储格式一致）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    """当前本地日期。

    **单独抽一个函数，是为了能注入。**
    结算系统每月只有 8、9 号能发起结算，如果各处直接写 ``date.today()``，
    就只有「今天正好是 8 号」时才跑得通完整链路 —— 测试根本没法覆盖
    「窗口内发起」这条主路径。统一走这里，测试用打补丁替换即可，
    生产代码里依然是真实的当前日期。

    另外支持环境变量 ``SETTLE_FAKE_TODAY``（YYYY-MM-DD）——
    纯本地演示用，让「窗口内发起结算」这条主路径在任何一天都能跑。
    """
    fake = os.environ.get(FAKE_TODAY_ENV, "").strip()
    if fake:
        try:
            return datetime.strptime(fake[:10], "%Y-%m-%d").date()
        except ValueError:
            # 格式不对就当没设，别让一个环境变量把整个服务搞挂
            pass
    return date.today()
