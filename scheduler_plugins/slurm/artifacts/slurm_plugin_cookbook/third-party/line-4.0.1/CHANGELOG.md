# Changelog

All notable changes to this project will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 4.0.1 - *2021-06-01*

## 4.0.0 - *2021-05-11*

- Greately increase the platforms we test in CI
- Increase the minimum supported Chef version to 15.3 for unified mode
- Remove code that was only there to support chef 12

## 2.9.3 - *2020-12-07*

- Add a type to the EOL property of the filter_lines resource

## 2.9.2 - *2020-12-06*

- resolved cookstyle error: libraries/filter_helper.rb:59:11 convention: `Style/CommentAnnotation`

## 2.9.1 (2020-09-16)

- resolved cookstyle error: libraries/filter_helper.rb:54:17 convention: `Style/BisectedAttrAccessor`
- resolved cookstyle error: libraries/filter_helper.rb:56:1 convention: `Layout/EmptyLines`
- resolved cookstyle error: libraries/filter_helper.rb:56:1 convention: `Layout/TrailingWhitespace`
- resolved cookstyle error: libraries/filter_helper.rb:56:17 convention: `Style/BisectedAttrAccessor`
- resolved cookstyle error: libraries/filter_helper.rb:57:1 convention: `Layout/EmptyLines`
- resolved cookstyle error: libraries/substitute_filter.rb:39:7 convention: `Style/RedundantAssignment`
- resolved cookstyle error: libraries/substitute_filter.rb:44:1 convention: `Layout/EmptyLinesAroundMethodBody`
- resolved cookstyle error: libraries/substitute_filter.rb:44:1 convention: `Layout/TrailingWhitespace`

## 2.9.0 (2020-06-18)

- Restore compatibility with Chef Infra Client < 16

## 2.8.1 - 2020-06-02

- resolved cookstyle error: resources/add_to_list.rb:10:1 warning: `ChefDeprecations/ResourceUsesOnlyResourceName`
- resolved cookstyle error: resources/append_if_no_line.rb:7:1 warning: `ChefDeprecations/ResourceUsesOnlyResourceName`
- resolved cookstyle error: resources/delete_from_list.rb:10:1 warning: `ChefDeprecations/ResourceUsesOnlyResourceName`
- resolved cookstyle error: resources/delete_lines.rb:7:1 warning: `ChefDeprecations/ResourceUsesOnlyResourceName`
- resolved cookstyle error: resources/filter_lines.rb:25:1 warning: `ChefDeprecations/ResourceUsesOnlyResourceName`
- resolved cookstyle error: resources/replace_or_add.rb:10:1 warning: `ChefDeprecations/ResourceUsesOnlyResourceName`

## [2.8.0] - 2020-03-06

- Feature - no duplicates
- Feature - next replace between
- Migrate to github actions
- Documentation fixes

## [2.7.0]

- Add new property remove_duplicates to add_or_replace resource
- Update documentation for the default value of the replace_only property in the add_or_replace resource

## [2.6.0] - 2019-12-19

- Add the :next boundary option to replace_between

```ruby
    This new options lets you replace delimited setting that extend over
    multiple lines. Adding :next to the boundary options find the next
    occurance of the search end pattern.

    Input file:
    logging = some, time, info,
              details;
    others = that;

    Desired output:
    logging = new, time, allinfo,
              details;
    others = that;

    Resource:
    replines = 'logging = new, time, allinfo,\ndetails;'
    filter_lines 'inputfile' do
      # :include makes sure to replace the matching lines
      # :next search for the first semicolon after matching logging =
      # The default behavior is to replace from the first match to the last
       filters(replace_between: [/^logging =/, /;/, replines, [:include,:next]])
    end
```

## [2.5.1]

- Replace_between examples had typos

## [2.5.0] - 2019-10-15

- Clean up processing of add and delete from lists
- Add processing of ends_with to delete from list
- Add unit tests for add and delete from list

## [2.4.1] - 2019-08-07

- Rename match_insert_lines to match_insert_lines?
- Add tests for match_insert_lines?

## [2.4.0]

- Add the replace_between filter to allow replacing all of the lines between two lines that match patterns.
- Change the test dangerfile name to samplefile.  There was a name conflict between the lint Dangerfile and the test data dangerfile that was causing some confusion.

## [2.3.3]

- Fix `filter_lines` to work with Chef12. The filters helper method matched the name of a resource property.
  Changed the name to avoid the collision.
- Add tests for the sensitive_default method
- Cookstyle comments

## [2.3.2]

- Fix internal documentation references
- Bump to get a rebuild

## [2.3.1]

- Try to make the links pretty on supermarket.chef.io.  Relative links did not translate well.

## [2.3.0]

- Add the between filter.
  Add lines between lines matching two patterns.
- Add the comment filter.
  Allow selected lines to be changed to comments in a file.
- Add the delete_before filter.
- Add the replace filter.
  Allow selected lines in a file to be replaced by other lines.
- Add the safe option to the after and before filter.
  Safe was the intended behavior.
- Add missing tests for methods verify_kind and verify_one_of.
- Allow inserted lines to be specified as strings. Split input strings on EOL characters.
- Add the substitute filter
- Add the stanza filter

## [2.2.0] - 2018-10-09

- Add the before filter method to allow lines to be inserted before a matching line.
- Add test examples that show combining filters.
- Add a couple tests of empty file edge cases.

## [2.1.1] - 2018-10-08

- Allow the backup option to be specified as true

## [2.1.0] - 2018-09-28

- Add the filter_lines resource
- Add the after filter method to allow lines to be inserted after matching a line

## [2.0.2] - 2018-06-29

- Explicitly disallow embedded EOL characters in replacement and append lines

## [2.0.1] - 2018-06-01

- Tested on chef 12.13.37.  Fix error caused by using the sensitive attribute.  Sensitive true will always be used for chef 12.

## [2.0.0] - 2018-05-19

- _Breaking change_ - Files are processed in memory instead of line by line. It's possible that large files that were previously updated by the line cookbook will not be able to be processed.
- _Breaking change_ - Drop Chef 12 support
- Use template files instead of `cookbook_file` so that we get platform sensitive line endings written for testing.
- Add windows support to `add_to_list`, `append_if_no_line`, `delete_from_list`, `delete_lines`, `replace_or_add`.
- Make the processing of missing target files consistent. Add the `ignore_missing` property to the resources to allow a missing file to raise an error.
- Clean up the order of some boiler plate code.
- Create helper methods for some common resource functions.
- Drop the OS helpers in favour os using `platform_family?`.

## [1.2.0] - 2018-04-18

- Add the ignore_missing option to the `delete_lines` and `delete_from_list`. Don't raise an error if the target file is missing.

## [1.1.1] - 2018-04-16

- Allow appending to an empty file.

## [1.1.0] - 2018-03-26

- Rework `delete_lines` to use file provider sub-resource.
- Support matching with regexps in addition to strings with `delete_lines`.
- Rework `append_if_no_line` to use file provider sub-resource.
- Fix edge conditions around `files-with-no-trailing-CR` being fed to `append_if_no_line`.
- Remove library helpers.
- Remove the `escape_regexp` and escape_string methods in favour of native `Regexp.escape`

## [1.0.6] - 2018-03-23

- Add question mark to regular expression escape characters

## [1.0.5] - 2018-02-20

- Minor Testing updates
- Remove custom matchers for ChefSpec. ChefDK 1 versions of ChefSpec will no longer work when unit testing against this cookbook.

## [1.0.4] - 2018-01-10

- Handle deleting items from a list using spaces as the delimeter

## [1.0.3] - 2017-08-22

- Add edge case tests for `add_to_list`
- Handle the `delete_lines`, `add_to_list`, and `delete_from_list` resources when a missing file is specified.

## [1.0.2] - 2017-07-07

- Fix #58 Add resource locator matchers
- Fix #59 Add resource matcher tests
- Make cookstyle 2.0.0 fixes
- Delete the unused minitest files
- Clean up the `file_ext` inspec resource

## [1.0.1] - 2017-07-05

- Fix #53 `append_if_no_line` appends line always appends

## [1.0.0] - 2017-06-13

- Move cookbook to Sous-Chefs org
- Move to using custom resources

## [0.6.3] - 2015-10-27

- Fixing Ruby and Chef deprecation warnings
- Cleaning up tests a bit
- Adding support for `source_url` and `issues_url`
- `delete_from_list` resource

## [0.6.2] - 2015-07-15

- Catch lines missed by strict patterns
- Add rspec tests for the `replace_or_add` provider. The existing chefspec tests don't step into the provider code and so don't check the provider functionality.
- Change the Gemfile to reflect the need for berkshelf 3, chefspec v4.2, rspec 3 for the tests.
- Update `provider_replace_or_add` to handle cases where the pattern does not match the replacement line.
- Fix notification problem where `updated_by_last_action` was set when nothing changed.

## [0.6.1] - 2015-02-24

- Adding CHANGELOG
- Adding ChefSpec matchers
