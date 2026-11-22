def calculate_charges(phone_minutes: int, internet_mb: int) -> tuple[int, int]:
    extra_minutes = max(0, phone_minutes - 1_000)
    extra_mb = max(0, internet_mb - 20_000)

    phone_blocks = (extra_minutes + 999) // 1_000
    internet_blocks = (extra_mb + 9_999) // 10_000

    return phone_blocks * 1_000, 5_000 + internet_blocks * 1_000
