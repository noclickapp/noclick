"""utils.phone_numbers.priced_country: the country a vendor that prices by
country (Twilio's SMS, Meta's WhatsApp) prices a number in."""

import pytest

from utils.phone_numbers import priced_country


@pytest.mark.parametrize("e164, country", [
    ("+14242421064", "US"),
    ("+14165550123", "CA"),     # a shared calling code's number by its own range
    ("+447911123456", "GG"),
    ("+447700900123", "GB"),    # a range no plan places: its calling code's main country
    ("+15550100", "US"),
    ("+919876543210", "IN"),
    ("+99912345678", None),     # no such calling code
    ("not a number", None),
])
def test_a_number_is_priced_in_its_own_country_else_its_calling_codes(e164, country):
    assert priced_country(e164) == country
