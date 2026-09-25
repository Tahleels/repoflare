from repoflare_core.domain.ids import stable_id


def test_stable_id_is_deterministic() -> None:
    assert stable_id("a", "b", "c") == stable_id("a", "b", "c")


def test_stable_id_distinguishes_part_boundaries() -> None:
    # "ab", "c" must not collide with "a", "bc" — this is what the 0x1f separator prevents.
    assert stable_id("ab", "c") != stable_id("a", "bc")


def test_stable_id_length() -> None:
    assert len(stable_id("x")) == 16
