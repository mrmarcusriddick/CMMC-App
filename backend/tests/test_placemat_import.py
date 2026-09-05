from app.placemat_import import services


def test_services_discards_blank_lines_and_normalizes_space():
    assert services("Microsoft Entra ID\n\xa0\nConditional Access\n") == ["Microsoft Entra ID", "Conditional Access"]
