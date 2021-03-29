$version: "1.0"

metadata validators = [
  {name: "CamelCase"},
  {name: "StutteredShapeName"},
  {name: "InputOutputStructureReuse"},
  {name: "MissingPaginatedTrait"},
  {name: "ShouldHaveUsedTimestamp"},
  {
    name: "EmitEachSelector",
    id: "OperationInputName",
    message: "This shape is referenced as input but the name does not end with 'Request'",
    configuration: {
      selector: "operation -[input]-> :not([id|name$=Request i])",
    },
  },
  {
    name: "EmitEachSelector",
    id: "OperationOutputName",
    message: "This shape is referenced as output but the name does not end with 'Response'",
    configuration: {
      selector: "operation -[output]-> :not([id|name$=Response i])",
    },
  },
]
