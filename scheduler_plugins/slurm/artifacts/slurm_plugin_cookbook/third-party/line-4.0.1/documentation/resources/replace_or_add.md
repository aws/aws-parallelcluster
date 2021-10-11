# Resource: replace_or_add

## Actions

| Action | Description                                                                                     |
| ------ | ----------------------------------------------------------------------------------------------- |
| edit   | Replace lines that match the pattern. Append the line unless a source line matches the pattern. |

## Properties

| Properties        | Description                              | Type                         | Values and Default                      |
| --------------    | ---------------------------------------- | ---------------------------- | --------------------------------------- |
| path              | File to update                           | String                       | Required, no default                    |
| pattern           | Regular expression to select lines       | Regular expression or String | Required, no default                    |
| line              | Line contents                            | String                       | Required, no default                    |
| replace_only      | Don't append only replace matching lines | true or false                | Default is false                        |
| remove_duplicates | Remove duplicate lines matching pattern  | true or false                | Default is false                        |
| ignore_missing    | Don't fail if the file is missing        | true or false                | Default is true                         |
| eol               | Alternate line end characters            | String                       | default `\n` on unix, `\r\n` on windows |
| backup            | Backup before changing                   | Boolean, Integer             | default false                           |

## Example Usage

```ruby
replace_or_add "why hello" do
  path "/some/file"
  pattern "Why hello there.*"
  line "Why hello there, you beautiful person, you."
end
```

```ruby
replace_or_add "change the love, don't add more" do
  path "/some/file"
  pattern "Why hello there.*"
  line "Why hello there, you beautiful person, you."
  replace_only true
end
```
