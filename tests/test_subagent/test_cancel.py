import threading
import time

from bourbon.subagent.cancel import AbortController


def test_abort_controller_initial_state():
    controller = AbortController()

    assert controller.is_aborted() is False


def test_abort_controller_abort():
    controller = AbortController()

    controller.abort()

    assert controller.is_aborted() is True


def test_abort_controller_parent_child():
    parent = AbortController()
    child = AbortController(parent=parent)

    parent.abort()

    assert child.is_aborted() is True


def test_abort_controller_child_does_not_affect_parent():
    parent = AbortController()
    child = AbortController(parent=parent)

    child.abort()

    assert parent.is_aborted() is False
    assert child.is_aborted() is True


def test_abort_controller_grandchild():
    grandparent = AbortController()
    parent = AbortController(parent=grandparent)
    child = AbortController(parent=parent)

    grandparent.abort()

    assert parent.is_aborted() is True
    assert child.is_aborted() is True


def test_child_created_after_parent_abort_is_aborted():
    parent = AbortController()
    parent.abort()

    child = AbortController(parent=parent)

    assert child.is_aborted() is True


def test_abort_controller_wait():
    controller = AbortController()

    def abort_after_delay():
        time.sleep(0.1)
        controller.abort()

    thread = threading.Thread(target=abort_after_delay)
    thread.start()

    result = controller.wait(timeout=1.0)
    thread.join()

    assert result is True
    assert controller.is_aborted() is True


def test_abort_controller_wait_timeout():
    controller = AbortController()

    result = controller.wait(timeout=0.01)

    assert result is False


def test_child_wait_unblocks_when_parent_aborts():
    parent = AbortController()
    child = AbortController(parent=parent)

    def abort_after_delay():
        time.sleep(0.1)
        parent.abort()

    thread = threading.Thread(target=abort_after_delay)
    thread.start()

    result = child.wait(timeout=1.0)
    thread.join()

    assert result is True
    assert child.is_aborted() is True
