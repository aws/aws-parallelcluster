# Examples for the between filter

## Original file

```text
line1
line2
line3
```

## Output file

```text
line1
line2
add1
add2
line3
```

## Filter

```ruby
addlines = "add1\nadd2\n"
filter_lines '/example/between' do
 filters(between: [/^line2$/, /^line3$/, addlines, :last])
end
```
