#include <bits/stdc++.h>
using namespace std;

#include <filesystem>

static string two(int x) {
	string s = to_string(x);
	if ((int)s.size() < 2) s = string(2 - (int)s.size(), '0') + s;
	return s;
}

int main(int argc, char** argv) {
	ios::sync_with_stdio(false);
	cin.tie(nullptr);

	if (argc < 4) {
		cerr << "Usage: gentest <tests_dir> <seed> <num_tests>\n";
		return 2;
	}

	const string testsDir = argv[1];
	const unsigned seed = (unsigned)stoull(argv[2]);
	const int numTests = max(1, stoi(argv[3]));

	mt19937 rnd(seed);
	auto rd = [&](int l, int r) {
		return uniform_int_distribution<int>(l, r)(rnd);
	};

    auto rdll = [&](long long l, long long r) {
    	return uniform_int_distribution<long long>(l, r)(rnd);
	};

	std::filesystem::create_directories(std::filesystem::path(testsDir));

	for (int t = 1; t <= numTests; ++t) {
		const string path = testsDir + "/" + two(t) + ".in";
		ofstream fout(path, ios::binary);
		if (!fout) {
			cerr << "Cannot write: " << path << "\n";
			return 3;
		}

		int n = rd(1, 1000000000);
        fout << n << '\n';
	}

	return 0;
}
