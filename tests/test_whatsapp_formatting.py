from app.services.whatsapp_service import format_text_for_whatsapp

def test_format_text_for_whatsapp_bold():
    raw_text = "Hello **David**, your booking is **confirmed**!"
    expected = "Hello *David*, your booking is *confirmed*!"
    assert format_text_for_whatsapp(raw_text) == expected

def test_format_text_for_whatsapp_headers():
    raw_text = "# Booking Summary\n## Court Details\nCourt 1"
    expected = "*BOOKING SUMMARY*\n*COURT DETAILS*\nCourt 1"
    assert format_text_for_whatsapp(raw_text) == expected

def test_format_text_for_whatsapp_strikethrough():
    raw_text = "The old price was ~~Rp 500.000~~ now Rp 400.000."
    expected = "The old price was ~Rp 500.000~ now Rp 400.000."
    assert format_text_for_whatsapp(raw_text) == expected

def test_format_text_for_whatsapp_combined():
    raw_text = "### Grand Slam Tennis\nWelcome **Luthfi**! Your court is ~~Court 2~~ Court 1."
    expected = "*GRAND SLAM TENNIS*\nWelcome *Luthfi*! Your court is ~Court 2~ Court 1."
    assert format_text_for_whatsapp(raw_text) == expected

def test_format_text_for_whatsapp_already_whatsapp():
    raw_text = "*Hello*, this is _italic_ and ~strike~."
    expected = "*Hello*, this is _italic_ and ~strike~."
    assert format_text_for_whatsapp(raw_text) == expected
