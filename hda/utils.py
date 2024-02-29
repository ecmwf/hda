import logging

logger = logging.getLogger(__name__)


def convert(query):
    """Converts a query in HDA v1 format into an HDA v2 one.
    Might not work in every case.
    If a v2 query is passed in, it is returned as is."""
    dataset_id = query.get("datasetId")

    if dataset_id is None and "dataset_id" in query:
        return query

    logger.warning(
        "The submitted query is still in HDA v1 format. "
        "It will be automatically converted, if possible, "
        "but it is recommended to update it manually."
    )

    # Modify the JSON query according to the new structure
    new_query = {"dataset_id": dataset_id}

    # Check if the original JSON has the "dateRangeSelectValues" field
    if "dateRangeSelectValues" in query:
        # Loop through the dateRangeSelectValues and add fields to new_query
        for date_range_value in query["dateRangeSelectValues"]:
            name = date_range_value["name"].lower()
            start = date_range_value["start"]
            end = date_range_value["end"]

            if dataset_id.startswith("EO:ECMWF:DAT:CAMS_"):
                new_query["dtstart"] = start
                new_query["dtend"] = end
            elif dataset_id.startswith("EO:CLMS:DAT:CGLS"):
                new_query["start"] = start
                new_query["end"] = end
            elif dataset_id.startswith("EO:MO:DAT:"):
                new_query["min_date"] = start
                new_query["max_date"] = end
            elif dataset_id.startswith("EO:EUM:DAT:"):
                new_query["dtstart"] = start
                new_query["dtend"] = end
            elif dataset_id.startswith("EO:EEA:DAT:CLMS_HRVPP"):
                new_query["start"] = start
                new_query["end"] = end
            elif dataset_id.startswith("EO:CNES:DAT:SWH"):
                new_query["creationDateStart"] = start
                new_query["creationDateEnd"] = end
            elif dataset_id.startswith("EO:ESA"):
                new_query["startDate"] = start
                new_query["completionDate"] = end
            else:
                new_query[f"{name}_start"] = start
                new_query[f"{name}_end"] = end

    if "boundingBoxValues" in query:
        new_query["bbox"] = query["boundingBoxValues"][0]["bbox"]

    # Add a "test" field for stringInputValues
    if "stringInputValues" in query:
        # Loop through the stringInputValues and add fields to new_query
        for string_input_value in query["stringInputValues"]:
            name = string_input_value["name"]
            value = string_input_value["value"]
            new_query[name] = value

    # Add a "test" field for stringChoiceValues
    if "stringChoiceValues" in query:
        # Loop through the stringChoiceValues and add fields to new_query
        for string_choice_value in query["stringChoiceValues"]:
            name = string_choice_value["name"]
            value = string_choice_value["value"]
            new_query[name] = value

    # Add a "test" field for multiStringSelectValues
    if "multiStringSelectValues" in query:
        # Loop through the stringChoiceValues and add fields to new_query
        for multi_string_select_value in query["multiStringSelectValues"]:
            name = multi_string_select_value["name"]
            value = multi_string_select_value["value"]
            new_query[name] = value

    return new_query
