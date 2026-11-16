"""The webshop world in Turtle: schema, knowledge base and the SHACL refund policy.

Everything is a plain string so it can be printed, edited in a notebook, or handed to a
model as context. The namespace is http://example.org/shop# with the prefix ``shop:``.
"""

NS = "http://example.org/shop#"

PREFIXES = """\
@prefix shop: <http://example.org/shop#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
"""

# Classes and properties. RDFS uses these to infer types; it never rejects anything.
SCHEMA_TTL = """\
shop:Person   a owl:Class .
shop:Customer a owl:Class ; rdfs:subClassOf shop:Person .
shop:Employee a owl:Class ; rdfs:subClassOf shop:Person .
shop:Manager  a owl:Class ; rdfs:subClassOf shop:Employee .
shop:AIAgent  a owl:Class ; rdfs:subClassOf shop:Employee .
shop:Order    a owl:Class .
shop:Refund   a owl:Class .

shop:placed      a owl:ObjectProperty ;   rdfs:domain shop:Customer ; rdfs:range shop:Order .
shop:forOrder    a owl:ObjectProperty ;   rdfs:domain shop:Refund ;   rdfs:range shop:Order .
shop:requestedBy a owl:ObjectProperty ;   rdfs:domain shop:Refund ;   rdfs:range shop:Customer .
shop:approvedBy  a owl:ObjectProperty ;   rdfs:domain shop:Refund ;   rdfs:range shop:Employee .
shop:amount      a owl:DatatypeProperty ; rdfs:domain shop:Refund ;   rdfs:range xsd:integer .
"""

# The facts the agent works against. Priya is a manager who is also a customer.
KB_TTL = """\
shop:lena    a shop:Customer ; shop:placed shop:o1001 , shop:o1002 .
shop:omar    a shop:Customer ; shop:placed shop:o1004 .
shop:priya   a shop:Manager , shop:Customer ; shop:placed shop:o1003 .
shop:marco   a shop:Manager .
shop:shopbot a shop:AIAgent .

shop:o1001 a shop:Order .
shop:o1002 a shop:Order .
shop:o1003 a shop:Order .
shop:o1004 a shop:Order .

shop:rf1 a shop:Refund ;
    shop:forOrder    shop:o1001 ;
    shop:requestedBy shop:lena ;
    shop:approvedBy  shop:priya ;
    shop:amount      25 .
"""

# The refund policy. Each constraint carries the message the agent will read back.
SHAPES_TTL = """\
shop:RefundShape a sh:NodeShape ;
    sh:targetClass shop:Refund ;
    sh:property [
        sh:path shop:amount ;
        sh:minCount 1 ;
        sh:maxInclusive 1000 ;
        sh:message "A refund needs an amount of at most 1000." ;
    ] ;
    sh:property [
        sh:path shop:amount ;
        sh:minExclusive 0 ;
        sh:message "The amount must be above 0." ;
    ] ;
    sh:property [
        sh:path shop:forOrder ;
        sh:minCount 1 ;
        sh:message "Name the order this refund is for." ;
    ] ;
    sh:property [
        sh:path shop:requestedBy ;
        sh:minCount 1 ;
        sh:message "A refund needs a requester." ;
    ] ;
    sh:property [
        sh:path shop:approvedBy ;
        sh:minCount 1 ;
        sh:message "A refund needs an approver." ;
    ] ;
    sh:property [
        sh:path shop:approvedBy ;
        sh:class shop:Manager ;
        sh:message "Only a Manager may approve a refund." ;
    ] ;
    sh:property [
        sh:path shop:approvedBy ;
        sh:disjoint shop:requestedBy ;
        sh:message "The approver must not be the person who requested the refund." ;
    ] ;
    sh:sparql [
        sh:message "The requester must be the customer who placed the order." ;
        sh:select '''
            SELECT $this WHERE {
                $this <http://example.org/shop#forOrder> ?order ;
                      <http://example.org/shop#requestedBy> ?requester .
                FILTER NOT EXISTS { ?requester <http://example.org/shop#placed> ?order }
            }
        ''' ;
    ] .

shop:OrderShape a sh:NodeShape ;
    sh:targetClass shop:Order ;
    sh:property [
        sh:path [ sh:inversePath shop:forOrder ] ;
        sh:maxCount 1 ;
        sh:message "An order can be refunded only once." ;
    ] .
"""

# Checked before the closure, on the proposal (door.py) and against the knowledge base (gate.py).
NOT_ONE_REFUND = "The proposal must describe exactly one refund."
NOTHING_ELSE = "The proposal may describe one refund and nothing else."
ID_IN_USE = "The refund id is already in use."
NO_SUCH_ORDER = "The order does not exist."
NO_SUCH_REQUESTER = "The requester does not exist."
NO_SUCH_APPROVER = "The approver does not exist."

# The SHACL messages, in the order the shapes declare them.
SHAPE_MESSAGES = (
    "A refund needs an amount of at most 1000.",
    "The amount must be above 0.",
    "Name the order this refund is for.",
    "A refund needs a requester.",
    "A refund needs an approver.",
    "Only a Manager may approve a refund.",
    "The approver must not be the person who requested the refund.",
    "The requester must be the customer who placed the order.",
    "An order can be refunded only once.",
)

# Every policy message the gate can give, in the order the gate checks the rules.
RULE_MESSAGES = (
    NOT_ONE_REFUND,
    NOTHING_ELSE,
    ID_IN_USE,
    NO_SUCH_ORDER,
    NO_SUCH_REQUESTER,
    NO_SUCH_APPROVER,
    *SHAPE_MESSAGES,
)
