# pip install psutil pywinctl
import contextlib as _contextlib
import os as _os
import psutil as _psutil
import pywinctl as _pywinctl  # type: ignore
import sys as _sys
import typing as _typing


def main() -> None:
    pid = int(input("PID: "))
    print(f"received: {pid}")
    pids = (pid,) + tuple(
        proc.pid for proc in _psutil.Process(pid).children(recursive=True)
    )
    print(f"PIDs: {pids}")

    windows: _typing.Collection[_pywinctl.Window] = _pywinctl.getAllWindows()
    print(f"windows: {windows}")
    for win in windows:
        win_pid = win_to_pid(win)
        if win_pid in pids:
            resizer(win_pid, win)
            break
    resizer(pid, None)


def win_to_pid(window: _pywinctl.Window) -> int | None:
    if _sys.platform == "darwin":
        return window._app.processIdentifier()
    elif _sys.platform == "linux":
        import ewmh as _ewmh

        return _ewmh.getWmPid(window.getHandle())
    elif _sys.platform == "win32":
        import win32process as _win32process

        return _win32process.GetWindowThreadProcessId(window.getHandle())[1]
    return None


def resizer(pid: int, window: _pywinctl.BaseWindow | None) -> None:
    print(f"window: {window}")
    r_in = resizer_in()
    r_out = resizer_out(pid, window)
    next(r_out)
    for size in r_in:
        r_out.send(size)


def resizer_in() -> _typing.Iterator[tuple[int, int]]:
    while True:
        size = _typing.cast(
            tuple[int, int],
            tuple(int(s.strip()) for s in input("size: ").split("x", 2)),
        )
        print(f"received: {'x'.join(map(str, size))}")
        yield size


def resizer_out(
    pid: int, window: _pywinctl.BaseWindow | None
) -> _typing.Generator[None, tuple[int, int], None]:
    if window is None:
        while True:
            yield
    window.hide()
    if _sys.platform == "win32":
        import pywintypes as _pywintypes
        import win32con as _win32con
        import win32console as _win32console
        import win32file as _win32file
        import win32gui as _win32gui

        @_typing.final
        class ConsoleScreenBufferInfo(_typing.TypedDict):
            Size: _win32console.PyCOORDType
            CursorPosition: _win32console.PyCOORDType
            Attributes: int
            Window: _win32console.PySMALL_RECTType
            MaximumWindowSize: _win32console.PyCOORDType

        def ignore_error(func: _typing.Callable[[], None]) -> bool:
            try:
                func()
                return True
            except _pywintypes.error:
                return False

        @_contextlib.contextmanager
        def attach_console(
            pid: int,
        ) -> _typing.Iterator[_win32console.PyConsoleScreenBufferType]:
            try:
                _win32console.AttachConsole(pid)  # type: ignore
                yield (_win32console.PyConsoleScreenBufferType)(  # type: ignore
                    _win32file.CreateFile(
                        "CONOUT$",
                        _win32file.GENERIC_READ | _win32file.GENERIC_WRITE,
                        _win32file.FILE_SHARE_WRITE,
                        None,
                        _win32file.OPEN_EXISTING,
                        0,
                        None,
                    )  # GetStdHandle gives the piped handle instead of the console handle
                )
            finally:
                _win32console.FreeConsole()

        while True:
            columns: int
            rows: int
            columns, rows = yield  # should be detached while waiting
            _win32console.FreeConsole()
            with attach_console(pid) as console:
                info: ConsoleScreenBufferInfo = (
                    console.GetConsoleScreenBufferInfo()  # type: ignore
                )
                old_rect = window.getClientFrame()
                old_actual_rect = window.size
                old_cols: int = (
                    info["Window"].Right - info["Window"].Left + 1  # type: ignore
                )
                old_rows: int = (
                    info["Window"].Bottom - info["Window"].Top + 1  # type: ignore
                )
                old_width = old_rect.right - old_rect.left
                old_height = old_rect.bottom - old_rect.top
                size = (
                    int(old_width * columns / old_cols)
                    + old_actual_rect.width
                    - old_width,
                    int(old_height * rows / old_rows)
                    + old_actual_rect.height
                    - old_height,
                )
                print(f"pixel size: {size}")
                setters = [
                    # almost accurate, works for alternate screen buffer
                    lambda: _win32gui.SetWindowPos(
                        _typing.cast(int, window.getHandle()),
                        None,
                        0,
                        0,
                        *size,
                        _win32con.SWP_NOACTIVATE
                        | _win32con.SWP_NOREDRAW
                        | _win32con.SWP_NOZORDER,
                    ),
                    # accurate, SetConsoleWindowInfo does not work for alternate screen buffer
                    lambda: (console.SetConsoleWindowInfo)(  # type: ignore
                        True,
                        _win32console.PySMALL_RECTType(0, 0, columns - 1, old_rows - 1),  # type: ignore
                    ),
                    lambda: console.SetConsoleScreenBufferSize(
                        _win32console.PyCOORDType(columns, old_rows)  # type: ignore
                    ),
                    lambda: (console.SetConsoleWindowInfo)(  # type: ignore
                        True,
                        _win32console.PySMALL_RECTType(0, 0, columns - 1, rows - 1),  # type: ignore
                    ),
                    lambda: console.SetConsoleScreenBufferSize(
                        _win32console.PyCOORDType(columns, rows)  # type: ignore
                    ),
                ]
                if old_cols < columns:
                    setters[1], setters[2] = setters[2], setters[1]
                if old_rows < rows:
                    setters[3], setters[4] = setters[4], setters[3]
                for setter in setters:
                    ignore_error(setter)
                print(f"resized")
    else:
        import termios as _termios

        @_contextlib.contextmanager
        def open_tty(pid: int) -> _typing.Iterator[int]:
            fd = _os.open(f"/proc/{pid}/fd/0", _os.O_RDONLY)
            try:
                yield fd
            finally:
                _os.close(fd)

        with open_tty(pid) as tty:
            while True:
                columns: int
                rows: int
                columns, rows = yield
                _termios.tcsetwinsize(tty, (rows, columns))
                print(f"resized")


if __name__ == "__main__":
    main()
