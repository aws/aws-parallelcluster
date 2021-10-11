Checklist for adding a new filter

README.md
    Note new filter
documentation/resources/filter_lines.md
    Filter parameters
kitchen.yml
    Add filter test case
resources/filter_lines.rb
    Update comment that lists builtin filters
test/fixtures/cookbooks/test/recipes/filter_documentation_examples.rb
    Add tests to execute the documentation examples
test/integration/filter_lines/controls/filter_documentation_examples_spec.rb
    Verify the results of the new documentation examples
documentation/resources/filters/replace_between.md
    Add the documentation examples
libraries/new_filter.rb
    Add the new filter
spec/unit/library/filter/new_filter.rb
    Rspec tests for basic function and edge cases of the new filter
test/fixtures/cookbooks/test/recipes/filter_lines_new_filter.rb
    Test idempotence of the new filter
test/integration/filter_lines/controls/filter_lines_new_filter_spec.rb
    Verify idempotence of the new filter
