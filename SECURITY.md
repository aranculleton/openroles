# Security

Please report a vulnerability privately, through GitHub's **Report a vulnerability**
button on this repository's Security tab, rather than in a public issue.

openroles only reads public job boards and never sends credentials, so the issues that
matter most are ones that would make it fetch somewhere it should not (a crafted board
response steering a request to another host), ignore robots.txt, or crash a caller on
hostile input. A fix for a confirmed report is released as soon as it is ready.
