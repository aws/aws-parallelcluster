# Resource: append_if_no_line

## Actions

| Action | Description                     |
| ------ | ------------------------------- |
| edit   | Append a line if it is missing. |

## Properties

| Properties     | Description                       | Type             | Values and Default                      |
| -------------- | --------------------------------- | ---------------- | --------------------------------------- |
| path           | File to update                    | String           | Required, no default                    |
| line           | Line contents                     | String           | Required, no default                    |
| ignore_missing | Don't fail if the file is missing | true or false    | Default is true                         |
| eol            | Alternate line end characters     | String           | default `\n` on unix, `\r\n` on windows |
| backup         | Backup before changing            | Boolean, Integer | default false                           |

## Example Usage

```ruby
append_if_no_line "make sure a line is in some file" do
  path "/some/file"
  line "HI THERE I AM STRING"
end
```

## Notes

This resource is intended to match the whole line **exactly**. That means if the file contains `this is my line` (trailing whitespace) and you've specified `line "this is my line"`, another line will be added. You may want to use `replace_or_add` instead, depending on your use case.
