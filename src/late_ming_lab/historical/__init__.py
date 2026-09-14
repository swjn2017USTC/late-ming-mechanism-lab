"""The historical core: a sourced Shaanxi-Henan dataset, and the rules that built it.

``inputs`` reads the raw snapshots, ``selection`` chooses the nodes, ``edges`` builds the three
movement graphs, ``forcing`` turns the documentary record into an annual index and allocates it,
``coverage`` reports what is covered, and ``build`` assembles, validates and stores the result.
Nothing here is a fixture: every value carries a source, a locator and a grade, or says it is a
declared rule of this project.
"""
