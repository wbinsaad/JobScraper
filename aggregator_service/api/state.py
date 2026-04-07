from fastapi import Request


def get_sync_task(request: Request):
    return request.app.state.sync_task


def get_con_factory(request: Request):
    return request.app.state.con_factory
