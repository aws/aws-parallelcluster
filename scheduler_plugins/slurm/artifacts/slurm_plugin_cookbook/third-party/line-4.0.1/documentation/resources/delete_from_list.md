# Resource: delete_from_list

## Actions

| Action | Description                |
| ------ | -------------------------- |
| edit   | Delete an item from a list |

## Properties

| Properties     | Description                        | Type                         | Values and Default                          |
| -------------- | ---------------------------------- | ---------------------------- | ------------------------------------------- |
| path           | File to update                     | String                       | Required, no default                        |
| pattern        | Regular expression to select lines | Regular expression or String | Required, no default                        |
| delim          | Delimiter entries                  | Array                        | Array of 1, 2 or 3 multi-character elements |
| entry          | Value to delete                    | String                       | Required, No default                        |
| ends_with      | List ending                        | String                       | No default                                  |
| ignore_missing | Don't fail if the file is missing  | true or false                | Default is true                             |
| eol            | Alternate line end characters      | String                       | default `\n` on unix, `\r\n` on windows     |
| backup         | Backup before changing             | Boolean, Integer             | default false                               |

## Example Usage

```ruby
delete_from_list "delete entry from a list" do
  path "/some/file"
  pattern "People to call: "
  delim [","]
  entry "Bobby"
end
```

## Notes

Delimiters are defined and used as in [add_to_list](https://github.com/sous-chefs/line/blob/master/documentation/resources/add_to_list.md).
