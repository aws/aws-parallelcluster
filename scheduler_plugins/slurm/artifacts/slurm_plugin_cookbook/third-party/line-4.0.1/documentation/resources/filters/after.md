# Examples for the after filter

## Original file

```text
line1
line2
```

## Output file

```text
line1
line2
add1
add2
```

## Filter

```ruby
addlines = "add1\nadd2\n"
or
addlines = ['add1', 'add2']
or
lines = <<~EOF
 add1
 add2
EOF
addlines= lines.gsub(/^\s+/,'')

filter_lines '/example/after' do
 filters(after: [/^line2$/, addlines, :last])
end
```
