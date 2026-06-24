import timeit

DICT_A = {
    'a': 1,
    'b': 2,
    'c': 3,
    'd': 4,
    'e': 5
}

DICT_B = {
    'f': 1,
    'g': 2,
    'h': 3,
    'i': 4,
    'j': 5
}

COMBINED_DICT_A = {**DICT_A, **DICT_B}
COMBINED_DICT_B = DICT_A | DICT_B

def item_lookup_merged_outside_a(ch: str) -> int | None:
    value = COMBINED_DICT_A[ch]
    if value is not None:
        return value
    return 0

def item_lookup_merged_outside_b(ch: str) -> int | None:
    value = COMBINED_DICT_B[ch]
    if value is not None:
        return value
    return 0


def item_lookup_merged_inside(ch: str) -> int | None:
    combined = {**DICT_A, **DICT_B}
    value = combined[ch]
    if value is not None:
        return value
    return 0

def item_lookup_not_merged(ch: str) -> int | None:
    value = DICT_A.get(ch)
    if value is not None:
        return value

    value = DICT_B.get(ch)
    if value is not None:
        return value
    return 0

it = 100_000_000

t = timeit.timeit(
    stmt="item_lookup_merged_outside_a('f')",
    setup="from __main__ import item_lookup_merged_outside_a",
    number=it
)
print(f"Merged Outside A: {t:.4f}s")

t = timeit.timeit(
    stmt="item_lookup_merged_outside_b('f')",
    setup="from __main__ import item_lookup_merged_outside_b",
    number=it
)
print(f"Merged Outside B: {t:.4f}s")

t = timeit.timeit(
    stmt="item_lookup_merged_inside('f')",
    setup="from __main__ import item_lookup_merged_inside",
    number=it,
)
print(f"Merged Inside: {t:.4f}s")

t = timeit.timeit(
    stmt="item_lookup_not_merged('f')",
    setup="from __main__ import item_lookup_not_merged",
    number=it
)
print(f"Not Merged: {t:.4f}s")