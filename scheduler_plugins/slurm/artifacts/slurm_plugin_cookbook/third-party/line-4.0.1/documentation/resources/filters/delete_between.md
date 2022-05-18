# Examples for the delete_between filter

## Original file

```text
line1
del1
del2
line2
del1
del2
line3
```

## Output file

```texttext
line1
del1
del2
line2
line3
```

## Filter

```ruby
filter_lines '/example/delete_between' do
 filters(delete_between: [/^line2$/, /^line3$/, /del/, :last])
end
```
