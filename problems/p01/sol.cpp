#include<bits/stdc++.h>
using namespace std;

int main() {
    int n;
    cin >> n;

    int cnt = 0;
    while (n > 0) {
        int r = n % 10;
        if (r == 0) ++cnt;
        else break;

        n /= 10;
    }

    cout << cnt << '\n';

    return 0;
}
