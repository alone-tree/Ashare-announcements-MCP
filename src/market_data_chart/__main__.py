"""支持 python -m chart_mcp。"""

from chart_mcp.server import create_server


if __name__ == "__main__":
    create_server().run()
