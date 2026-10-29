"""Helpers for safe spreadsheet exports."""


def escape_formula_cells(workbook):
    """Force untrusted text beginning with spreadsheet formula characters to literals."""
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.lstrip("\t\r\n ").startswith(("=", "+", "-", "@")):
                    cell.value = "'" + value
    return workbook
