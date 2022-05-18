# Resource: add_to_list

## Actions

| Action | Description           |
| ------ | --------------------- |
| edit   | Add an item to a list |

## Properties

| Properties     | Description                        | Type                         | Values and Default                          |
| -------------- | ---------------------------------- | ---------------------------- | ------------------------------------------- |
| path           | File to update                     | String                       | Required, no default                        |
| pattern        | Regular expression to select lines | Regular expression or String | Required, no default                        |
| delim          | Delimiter entries                  | Array                        | Array of 1, 2 or 3 multi-character elements |
| entry          | Value to add                       | String                       | Required, No default                        |
| ends_with      | List ending                        | String                       | No default                                  |
| ignore_missing | Don't fail if the file is missing  | true or false                | Default is true                             |
| eol            | Alternate line end characters      | String                       | default `\n` on unix, `\r\n` on windows     |
| backup         | Backup before changing             | Boolean, Integer             | default false                               |

## Example Usage

```ruby
add_to_list "add entry to a list" do
  path "/some/file"
  pattern "People to call: "
  delim [","]
  entry "Bobby"
end
```

## Notes

If one delimiter is given, it is assumed that either the delimiter or the given search pattern will proceed each entry and each entry will be followed by either the delimiter or a new line character.

```text
Example:
Input -      People to call: Joe, Bobby
Delimeters - delim [","]
Add this -   entry 'Karen'
Output -     People to call: Joe, Bobby, Karen
```

If two delimiters are given, the first is used as the list element delimiter and the second as entry delimiters.

```text
Example:
Input -      net1918 = "10.0.0.0/8", "172.16.0.0/12"
Delimeters - delim [", ", "\""]
Add this -   entry "192.168.0.0/16"
Output -     net1918 = "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
```

If three delimiters are given, the first is used as the list element delimiter, the second as the leading entry delimiter and the third as the trailing delimiter.

```text
Example:
Input -      multi = ([310], [818])
Delimeters - delim [", ", "[", "]"]
Add this -   entry "425"
Output -     multi = ([310], [818], [425])
```

`ends_with` is an optional property. If specified, a list is expected to end with the given string.
This property is useful for inserting into an empty delimited list.

```text
Example:
Input -      multi = "()"
Delimeters - delim [", ", "[", "]"]
Ends With -  ')"'
Pattern -    'multi = "'
Add this -   entry "425"
Output -     multi = "([425])"
```
