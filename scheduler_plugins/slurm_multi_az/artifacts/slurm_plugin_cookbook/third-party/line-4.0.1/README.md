# line cookbook

[![Cookbook Version](https://img.shields.io/cookbook/v/line.svg)](https://supermarket.chef.io/cookbooks/line)
[![CI State](https://github.com/sous-chefs/line/workflows/ci/badge.svg)](https://github.com/sous-chefs/line/actions?query=workflow%3Aci)
[![OpenCollective](https://opencollective.com/sous-chefs/backers/badge.svg)](#backers)
[![OpenCollective](https://opencollective.com/sous-chefs/sponsors/badge.svg)](#sponsors)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](https://opensource.org/licenses/Apache-2.0)

## Maintainers

This cookbook is maintained by the Sous Chefs. The Sous Chefs are a community of Chef cookbook maintainers working together to maintain important cookbooks. If you’d like to know more please visit [sous-chefs.org](https://sous-chefs.org/) or come chat with us on the Chef Community Slack in [#sous-chefs](https://chefcommunity.slack.com/messages/C2V7B88SF).

## Motivation

Quite often, the need arises to do line editing instead of managing an entire file with a template resource. This cookbook supplies various resources that will help you do this.

## Limitations

- The line resources processes the entire target file in memory. Trying to edit large files may fail.
- The end of line processing was only tested using `\n` and `\r\n`. Using other line endings very well may not work.
- The end of line string used needs to match the actual end of line used in the file `\n` and `\r\n` are used as the defaults but if they don't match the actual end of line used in the file the results will be weird.
- Adding a line implies there is a separator on the previous line. Adding a line differs from appending characters.
- Lines to be added should not contain EOL characters. The providers do not do multiline regex checks.
- Missing file processing is the way it is by intention

  - `add_to_list` do nothing, list not found so there is nothing to add to.
  - `append_if_no_line` create file, add the line.
  - `delete_from_list` do nothing, the list was not found which implies there is nothing to delete
  - `delete_lines` do nothing, the line isn't there which implies there is nothing to delete
  - `replace_or_add` create file, add the line
  - `filter_lines` create file if the file changes

- Chef client version 13 or greater is expected.

## Resources

For more detailed information see the matching resource documentation:

- [append_if_no_line](https://github.com/sous-chefs/line/blob/master/documentation/resources/append_if_no_line.md) - Add a missing line
- [replace_or_add](https://github.com/sous-chefs/line/blob/master/documentation/resources/replace_or_add.md) - Replace a line that matches a pattern or add a missing line
- [delete_lines](https://github.com/sous-chefs/line/blob/master/documentation/resources/delete_lines.md) - Delete lines that match a pattern
- [add_to_list](https://github.com/sous-chefs/line/blob/master/documentation/resources/add_to_list.md) - Add an item to a list
- [delete_from_list](https://github.com/sous-chefs/line/blob/master/documentation/resources/delete_from_list.md) - Delete an item from a list
- [filter_lines](https://github.com/sous-chefs/line/blob/master/documentation/resources/filter_lines.md) - Supply a ruby proc or use a sample filter to edit lines.
  The filter_lines resource supports multiple line modfications.

### Sample filters

- after: Insert lines after a matched line
- before: Insert lines before a matched lined
- between: Insert lines between matched lines
- comment: Change lines to comments
- delete_between: Delete the lines found between two patterns
- missing: Add missing lines to a file
- replace: Replace each instance of matched lines
- replace_between: Replace lines between matched lines
- stanza: Insert or change keys in files formatted in stanzas
- substitute: Substitute text in lines matching a pattern

## Authors

- Contributor: Mark Gibbons
- Contributor: Dan Webb
- Contributor: Sean OMeara
- Contributor: Antek S. Baranski

## Contributors

This project exists thanks to all the people who [contribute.](https://opencollective.com/sous-chefs/contributors.svg?width=890&button=false)

### Backers

Thank you to all our backers!

![https://opencollective.com/sous-chefs#backers](https://opencollective.com/sous-chefs/backers.svg?width=600&avatarHeight=40)

### Sponsors

Support this project by becoming a sponsor. Your logo will show up here with a link to your website.

![https://opencollective.com/sous-chefs/sponsor/0/website](https://opencollective.com/sous-chefs/sponsor/0/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/1/website](https://opencollective.com/sous-chefs/sponsor/1/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/2/website](https://opencollective.com/sous-chefs/sponsor/2/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/3/website](https://opencollective.com/sous-chefs/sponsor/3/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/4/website](https://opencollective.com/sous-chefs/sponsor/4/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/5/website](https://opencollective.com/sous-chefs/sponsor/5/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/6/website](https://opencollective.com/sous-chefs/sponsor/6/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/7/website](https://opencollective.com/sous-chefs/sponsor/7/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/8/website](https://opencollective.com/sous-chefs/sponsor/8/avatar.svg?avatarHeight=100)
![https://opencollective.com/sous-chefs/sponsor/9/website](https://opencollective.com/sous-chefs/sponsor/9/avatar.svg?avatarHeight=100)
