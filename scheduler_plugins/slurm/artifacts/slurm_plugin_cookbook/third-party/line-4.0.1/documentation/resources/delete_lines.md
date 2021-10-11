# Resource: delete_lines

## Actions

| Action | Description                          |
| ------ | ------------------------------------ |
| edit   | Delete lines that match the pattern. |

## Properties

| Properties     | Description                        | Type                         | Values and Default                      |
| -------------- | ---------------------------------- | ---------------------------- | --------------------------------------- |
| path           | File to update                     | String                       | Required, no default                    |
| pattern        | Regular expression to select lines | Regular expression or String | Required, no default                    |
| ignore_missing | Don't fail if the file is missing  | true or false                | Default is true                         |
| eol            | Alternate line end characters      | String                       | default `\n` on unix, `\r\n` on windows |
| backup         | Backup before changing             | Boolean, Integer             | default false                           |

## Example Usage

```ruby
delete_lines "remove hash-comments from /some/file" do
  path "/some/file"
  pattern "^#.*"
end
```

```ruby
delete_lines "remove hash-comments from /some/file with a regexp" do
  path "/some/file"
  pattern /^#.*/
end
```

```ruby
delete_lines 'remove from nonexisting' do
  path '/tmp/doesnotexist'
  pattern /^#/
  ignore_missing true
end
```

## Notes

Removes lines based on a string or regex.
